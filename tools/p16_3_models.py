#!/usr/bin/env python3
"""(2026-11-25 P16-3) 코치 턴 모델 비교 — 제품 코드는 읽기만 한다(대화 엔진을 고치지 않는다).

P16-2 실세션 재실행을 사용자가 읽고 판정했다: 되받기는 사라졌지만 딱딱하고, 짧고 맥락 없는 질문·두세 가지를 한꺼번에 묻는 질문·말하지 않은 것을 전제로 한 질문이
있고, 초반의 퉁명스러운 답에 '네.'로 넘어가는 것이 걸린다. 지금 대화 모델(Haiku)은 처음 쓴 질문이 대부분 되받는 앞 절로 시작해 코드로 잘라 내고 있다.
같은 지시문·같은 입력으로 두 모델이 쓴 것을 나란히 놓는다. 출력은 다듬지 않고 다시 쓰게 하지도 않는다.

  H  지금 대화에 쓰는 모델(Haiku)
  S  지금 분석에 쓰는 모델(Sonnet)

지점(11/25 Lucas 조직관리 실세션): 라포 3곳(R1~R3) · 영역 정의 받는 말 1곳(A1) · 사례 지점 13곳(C1~C13 — 중간 10 + 마무리 자리 3).
입력은 그 시점까지의 실제 대화 전체다. 사례 지점에는 영역 정의·하위역량·수준 기준(하위역량 서술과 수준을 가르는 조건)도 준다. '덜 찬 칸' 이름은 주지 않는다.
지시는 원칙만 적는다(예시 문장 없음).

정한 것(지시에 없던 것):
  · 라포에서 다음 질문(되물음·맡은 일·기대)은 운영에서 고정 문구다 — 모델에는 받는 말만 쓰게 하고, 이어질 질문을 입력으로 알려 준다.
  · 사례 지점의 대화 전체에서 지금 다루는 일이 시작된 코치 질문에 표시(▶)를 붙인다(다른 일의 내용을 끌어오지 말라는 지시가 가리키는 경계).

사용(워크트리 루트에서):
    python tools/p16_3_models.py --transcript ../sim/real_20261125_lucas_org.md --dry-run            # 지점과 지시문·입력만(호출 없음)
    python tools/p16_3_models.py --transcript ../sim/real_20261125_lucas_org.md --points C13         # 한 지점만(비용 확인)
    python tools/p16_3_models.py --transcript ../sim/real_20261125_lucas_org.md                      # 17개 지점 전부(이미 돌린 지점은 다시 부르지 않는다)
출력(--out, 기본 전문과 같은 폴더): p16_3_blind.md(가림 판) · p16_3_key.md(정답표·집계) · p16_3_raw.json(원자료)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import p16_compare as PC  # noqa: E402

COACH = "Lucas"
CHAPTER = "organization_management"
SESSION_TURNS = 150

_COMMON = (
    "당신은 경험 많은 역량 면접관입니다. 리더와 마주 앉아 말하듯 자연스럽게 말합니다. 조서를 받는 말투가 되지 않게 합니다.\n\n"
    "[공통]\n"
    "- 리더가 한 말을 되풀이하지 않는다. 문장으로도, 질문 앞에 붙는 절로도 옮기지 않는다. 가리켜야 하면 명사구 하나로 가리킨다.\n"
    "- 리더가 말하지 않은 것을 전제로 삼지 않는다. 지금 다루는 일이 아닌 다른 일(앞서 끝난 이야기)의 내용을 끌어오지 않는다. 이미 답한 것을 다시 묻지 않는다.\n"
    "- 코치가 할 말만 쓴다. 설명·머리말·번호·따옴표를 붙이지 않는다.\n\n"
)
_KIND = {
    "mid": (
        "[이번 턴 — 지금 다루는 일의 중간]\n"
        "- 질문은 하나다. 리더가 방금 한 답의 구체적인 대목 하나를 짚어 이야기를 청한다.\n"
        "- 무엇을 물을지: 리더 본인의 행동·판단, 사람(팀원·상대)과의 과정, 결과의 크기, 그 방식이 팀에 남았는지와 팀 밖으로 이어졌는지 — "
        "이 가운데 지금까지 가장 덜 드러난 것.\n"
        "- 반응은 꼭 어울릴 때만 붙인다. 붙인다면 리더가 쓰지 않은 말로 짧게, 상황의 어려움을 알아주거나 뜻을 한마디로 짚는다. "
        "바로 앞 코치 턴에 반응이 있었으면 이번에는 질문만 쓴다. 평가와 칭찬은 하지 않는다.\n"
        "- 수준 기준은 코치만 보는 자료다. 수준 이름이나 하위역량 이름은 말하지 않는다.\n"
        "- 이 일에 대해 충분히 들었으면 질문 대신 [닫음] 이라고 쓰고 이유를 한 줄로 적는다.\n\n"
    ),
    "wrap": (
        "[이번 턴 — 지금 다루는 일의 마무리]\n"
        "- 이해한 요지를 한 문장(스무 어절 이하)으로 적고, 이어서 확인할 것 하나를 짧게 묻는 질문을 쓴다.\n"
        "- 하나만 더 확인하겠다고 알리는 말은 두 문장 사이에 따로 들어가므로 쓰지 않는다.\n"
        "- 수준 기준은 코치만 보는 자료다. 수준 이름이나 하위역량 이름은 말하지 않는다.\n"
        "- 물을 것이 없으면 [닫음] 이라고만 쓴다.\n\n"
    ),
    "rapport": (
        "[이번 턴 — 본론에 들어가기 전의 가벼운 대화]\n"
        "- 리더가 방금 한 말을 옮기지 않고, 사람답게 가볍게 받는 말만 쓴다. 열 어절 이하.\n"
        "- 짧고 퉁명스러운 답에도 자연스럽게 받는다.\n"
        "- 받는 말 뒤에는 입력의 [이어질 질문]이 그대로 붙는다. 그 질문은 쓰지 않는다. 다른 질문도 하지 않는다.\n\n"
    ),
    "align": (
        "[이번 턴 — 영역 정의 답을 받는 말]\n"
        "- 리더가 이 영역을 어떤 일로 보는지 방금 답했다. 그 정의를 그대로 옮기지 않고 요지를 한마디로 받는 한 문장을 쓴다. 열다섯 어절 이하.\n"
        "- 받는 말 뒤에는 정해진 안내와 첫 질문이 따로 붙는다. 질문이나 안내는 쓰지 않는다.\n\n"
    ),
}


def build_system(kind: str) -> str:
    from diag_project.services.persona_register import register_hint
    return _COMMON + _KIND[kind] + f"[말투] {register_hint(COACH)} 리더를 부를 때는 '리더님'이라고만 한다."


def _convo(turns: list[tuple[str, str]], mark: int | None = None) -> str:
    return "\n".join(f"{'▶ ' if i == mark else ''}{'코치' if r == 'model' else '리더'}: {t}" for i, (r, t) in enumerate(turns))


def build_user(point: dict) -> str:
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK
    from diag_project.services import coach_v2 as V
    kind = point["kind"]
    if kind in ("mid", "wrap"):
        comp = COMPETENCY_FRAMEWORK[CHAPTER]
        sub_name = comp["indicators"][point["sub"]]["name"] if point.get("sub") in comp["indicators"] else None
        return (
            f"[영역] {comp['name']} — {comp['description']}\n"
            f"[지금 다루는 하위역량] {sub_name or '(가려내지 못함 — 이 영역의 하위역량 전체를 참고)'}\n\n"
            f"[수준 기준 — 코치만 보는 자료]\n{V.level_block(CHAPTER, sub_name)}\n\n"
            f"[지금까지의 대화 전체 — 마지막 줄이 리더가 방금 한 답. 지금 다루는 일은 ▶ 가 붙은 코치 질문에서 시작했다]\n{_convo(point['history'], point['open_i'])}\n\n"
            "이제 코치가 할 말을 씁니다."
        )
    tail = f"[이어질 질문]\n{point['next_q']}\n\n" if kind == "rapport" else ""
    return f"[지금까지의 대화 전체 — 마지막 줄이 리더가 방금 한 답]\n{_convo(point['history'])}\n\n{tail}이제 코치가 할 말을 씁니다."


def locate(turns: list[tuple[str, str]]) -> list[dict]:
    """17개 지점 — 라포 3(이름 답 다음의 세 답) · 영역 정의 답 1 · 사례 지점 13(p16_compare.locate_auto 와 같은 자리)."""
    from diag_project.services.output_guard import is_question, split_sentences
    ch0 = PC.chapter_start(turns, CHAPTER)
    out: list[dict] = []
    users = [i for i in range(ch0) if turns[i][0] == "user"]
    for n, i in enumerate(users[1:4], 1):
        actual = turns[i + 1][1]
        nq = [x.strip() for x in split_sentences(actual) if x.strip()]
        k = next((j for j, x in enumerate(nq) if is_question(x)), len(nq) - 1)
        out.append({"id": f"R{n}", "kind": "rapport", "leader": turns[i][1], "actual": actual, "history": turns[:i + 1], "next_q": " ".join(nq[k:])})
    d_i = next(i for i in range(ch0 + 1, len(turns)) if turns[i][0] == "user")
    out.append({"id": "A1", "kind": "align", "leader": turns[d_i][1], "actual": turns[d_i + 1][1].split("\n")[0], "history": turns[:d_i + 1]})
    for p in PC.locate_auto(turns, CHAPTER):
        i = p["turn_index"]
        out.append({"id": f"C{p['n']}", "kind": p["kind"], "leader": p["leader"], "actual": p["actual"], "history": turns[:i + 1],
                    "open_i": i + 1 - len(p["case"]), "sub": p["sub"]})
    return out


# ── 집계(자동으로 셀 수 있는 것) ─────────────────────────────────────────────────────────────
def is_close(text: str) -> bool:
    return "[닫음]" in (text or "") or re.sub(r"[\s\[\]]+", "", text or "")[:2] == "닫음"


def echo_start(text: str, point: dict) -> tuple[bool, str]:
    """직전 답을 되받으며 시작했는가 — 사례 지점: 첫 문장(평서문)이나 질문의 앞 절이 직전 답과 내용 낱말 둘 이상 겹침.
    라포: 리더 말을 그대로 옮김(이어진 네 글자 또는 내용 낱말 둘 이상). 영역 정의: 리더 문장을 이어서 네 어절 이상 옮김."""
    from diag_project.services.output_guard import echoes_user, is_question, split_sentences
    from diag_project.services.turn_checks import borrowed_run, question_first_clause, receive_shared_words
    t, ans = (text or "").strip(), point["leader"]
    if not t or is_close(t):
        return False, ""
    if point["kind"] == "rapport":
        sh = receive_shared_words(t, ans)
        return (bool(echoes_user(t, ans)) or len(sh) >= 2), f"겹친 낱말 {len(sh)}"
    if point["kind"] == "align":
        run = borrowed_run(t, ans)
        return run >= 4, f"이어서 옮긴 어절 {run}"
    ss = [x.strip() for x in split_sentences(t) if x.strip()]
    head = ss[0] if not is_question(ss[0]) else (question_first_clause(ss[0]) or "")
    sh = receive_shared_words(head, ans) if head else []
    return len(sh) >= 2, (f"{'평서문' if not is_question(ss[0]) else '앞 절'} · 겹친 낱말 {len(sh)}" if head else "바로 질문")


def ask_count(text: str) -> tuple[int, bool]:
    """(물음의 수, 둘 가운데 고르게 하는 꼴인가) — 질문 문장 수와 한 문장 안의 두 물음(coach_v2.two_asks)을 합쳐 센다."""
    from diag_project.services import coach_v2 as V
    from diag_project.services.output_guard import is_question, split_sentences
    if is_close(text):
        return 0, False
    qs = [x.strip() for x in split_sentences(text or "") if x.strip() and is_question(x)]
    alt = any(V._ALT_RE.search(q) for q in qs)
    return len(qs) + sum(1 for q in qs if V.two_asks(q) and not V._ALT_RE.search(q)), alt


def aggregate(points: list[dict], raw: dict, tag: str) -> dict:
    rows = [(p, raw[p["id"]][tag]) for p in points if raw.get(p["id"])]
    case = [(p, r) for p, r in rows if p["kind"] in ("mid", "wrap")]
    said = [(p, r) for p, r in rows if not is_close(r["text"])]
    echo = [(p["id"], echo_start(r["text"], p)[1]) for p, r in said if echo_start(r["text"], p)[0]]
    multi = [p["id"] for p, r in said if ask_count(r["text"])[0] >= 2]
    alt = [p["id"] for p, r in said if ask_count(r["text"])[1]]
    sec = sorted(r["sec"] for _p, r in rows)
    sec_case = sorted(r["sec"] for _p, r in case)
    usd_case = [r["usd"] for _p, r in case]
    return {"n": len(rows), "echo": echo, "multi": multi, "alt": alt, "close": [p["id"] for p, r in rows if is_close(r["text"])],
            "eojeol_case": round(statistics.mean([len(r["text"].split()) for p, r in case if not is_close(r["text"])] or [0]), 1),
            "eojeol_all": round(statistics.mean(len(r["text"].split()) for _p, r in said), 1) if said else 0,
            "sec_med": statistics.median(sec) if sec else 0, "sec_max": sec[-1] if sec else 0,
            "sec_case_med": statistics.median(sec_case) if sec_case else 0, "sec_case_max": sec_case[-1] if sec_case else 0,
            "usd_total": round(sum(r["usd"] for _p, r in rows), 4), "usd_case_avg": round(statistics.mean(usd_case), 5) if usd_case else 0,
            "in_case_avg": int(statistics.mean(r["in"] for _p, r in case)) if case else 0, "out_case_avg": int(statistics.mean(r["out"] for _p, r in case)) if case else 0}


def write_outputs(points: list[dict], raw: dict, out_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    names = {"rapport": "라포", "align": "영역 정의 받는 말", "mid": "사례 중간 턴", "wrap": "사례 마무리 자리"}
    L = ["# P16-3 코치 턴 모델 비교 — 가림 판", "",
         "지점마다 리더가 방금 한 답(앞 60자)과 후보 둘입니다. 같은 지시문·같은 입력으로 두 모델이 쓴 것을 다듬지 않고 그대로 실었습니다.",
         "순서는 지점마다 섞었고, 어느 모델인지는 적지 않았습니다.", "",
         "- 라포: 후보는 받는 말입니다. 그 뒤에 '이어질 질문'(운영에서 고정 문구)이 그대로 붙습니다.",
         "- 영역 정의: 후보는 받는 말 한 문장입니다. 그 뒤에 정해진 안내와 첫 질문이 붙습니다.",
         "- 사례 마무리 자리: 운영에서는 두 문장 사이에 '하나만 더 확인하겠습니다' 같은 고정 문구가 들어갑니다.", ""]
    K = ["# P16-3 코치 턴 모델 비교 — 정답표", "", "H = 지금 대화에 쓰는 모델(Haiku) · S = 지금 분석에 쓰는 모델(Sonnet)", "",
         "| 지점 | 종류 | 가 | 나 | H 비용(USD) | H 지연(초) | S 비용(USD) | S 지연(초) |", "|---|---|---|---|---|---|---|---|"]
    for p in points:
        r = raw.get(p["id"])
        if not r:
            continue
        cands = [("H", r["H"]["text"]), ("S", r["S"]["text"])]
        rng.shuffle(cands)
        lead = p["leader"] if len(p["leader"]) <= 60 else p["leader"][:60] + "…"
        L += [f"## {p['id']} — {names[p['kind']]}", f"리더: {lead}"]
        if p["kind"] == "rapport":
            L.append(f"이어질 질문(고정): {p['next_q']}")
        L.append("")
        for lab, (_k, t) in zip("가나", cands):
            L.append(f"- **{lab}**: {t}")
        L.append("")
        K.append(f"| {p['id']} | {names[p['kind']]} | " + " | ".join(k for k, _t in cands)
                 + f" | {r['H']['usd']:.5f} | {r['H']['sec']} | {r['S']['usd']:.5f} | {r['S']['sec']} |")
    K += ["", "## 모델별 집계(자동으로 센 것 — 말하지 않은 전제·다른 사례 내용은 읽어서 판정해 보고에 따로 적는다)", "",
          "| 항목 | H(Haiku) | S(Sonnet) |", "|---|---|---|"]
    a = {t: aggregate(points, raw, t) for t in ("H", "S")}
    row = lambda label, fn: K.append(f"| {label} | {fn(a['H'])} | {fn(a['S'])} |")      # noqa: E731
    row("지점 수", lambda v: v["n"])
    row("직전 답을 되받으며 시작한 턴", lambda v: f"{len(v['echo'])} ({', '.join(i for i, _w in v['echo']) or '-'})")
    row("한 턴에 물음이 둘 이상인 턴", lambda v: f"{len(v['multi'])} ({', '.join(v['multi']) or '-'})")
    row("둘 가운데 고르게 하는 꼴(따로 셈)", lambda v: f"{len(v['alt'])} ({', '.join(v['alt']) or '-'})")
    row("[닫음]", lambda v: f"{len(v['close'])} ({', '.join(v['close']) or '-'})")
    row("평균 어절 — 사례 지점 / 전체", lambda v: f"{v['eojeol_case']} / {v['eojeol_all']}")
    row("지연 중앙값 / 최대(초) — 전체", lambda v: f"{v['sec_med']} / {v['sec_max']}")
    row("지연 중앙값 / 최대(초) — 사례 지점", lambda v: f"{v['sec_case_med']} / {v['sec_case_max']}")
    row("사례 지점 턴당 비용(USD) · 입력/출력 토큰 평균", lambda v: f"{v['usd_case_avg']:.5f} · {v['in_case_avg']}/{v['out_case_avg']}")
    row(f"세션({SESSION_TURNS}턴) 환산(USD) — 사례 지점 턴당 비용 기준", lambda v: f"{v['usd_case_avg'] * SESSION_TURNS:.2f}")
    row("이번 실험 비용 합계(USD)", lambda v: f"{v['usd_total']:.4f}")
    K += ["", f"실제 비용 합계: ${a['H']['usd_total'] + a['S']['usd_total']:.4f}",
          "", "환산의 바탕: 이 실험의 입력은 그 시점까지의 대화 전체다(운영의 사례 중간 턴 입력은 그 사례의 대화와 이 영역에서 코치가 한 말이라 더 짧다)."]
    (out_dir / "p16_3_blind.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (out_dir / "p16_3_key.md").write_text("\n".join(K) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="P16-3 코치 턴 모델 비교(제품 코드 수정 없음)")
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--points", default="", help="쉼표로 나눈 지점 이름(R1~R3, A1, C1~C13). 비우면 전부")
    ap.add_argument("--dry-run", action="store_true", help="지점과 지시문·입력만 출력한다(LLM 호출 없음)")
    ap.add_argument("--no-run", action="store_true", help="호출하지 않고 있는 원자료로 출력만 다시 만든다")
    ap.add_argument("--seed", type=int, default=20261125)
    args = ap.parse_args(argv)
    path = Path(args.transcript)
    out_dir = Path(args.out) if args.out else path.parent
    points = locate(PC.parse_transcript(path.read_text(encoding="utf-8")))
    want = [x.strip() for x in args.points.split(",") if x.strip()]
    for p in points:
        print(f"{p['id']:>3} [{p['kind']}] 대화 {len(p['history'])}턴 · 입력 {len(build_user(p))}자 · 리더: {p['leader'][:40]}")
    if args.dry_run:
        for k in ("mid", "wrap", "rapport", "align"):
            print(f"\n===== 지시문({k}) =====\n{build_system(k)}")
        print("\n===== 입력(C1) =====\n" + build_user(next(p for p in points if p["id"] == "C1"))[-900:])
        print("\n===== 입력(R2) =====\n" + build_user(next(p for p in points if p["id"] == "R2")))
        return 0
    raw_path = out_dir / "p16_3_raw.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.exists() else {}
    if not args.no_run:
        from diag_project.llm_service import GeminiService
        llm = GeminiService().bind_provider("claude")

        async def run() -> None:
            for p in points:
                if (want and p["id"] not in want) or raw.get(p["id"]):
                    continue
                system, user = build_system(p["kind"]), build_user(p)
                h = await PC.call(llm, system=system, user=user, sonnet=False)
                s = await PC.call(llm, system=system, user=user, sonnet=True)
                raw[p["id"]] = {"H": h, "S": s, "kind": p["kind"]}
                raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"{p['id']}: H ${h['usd']:.5f} {h['sec']}초 {h['in']}/{h['out']}토큰 ({h['model']}) · S ${s['usd']:.5f} {s['sec']}초 {s['in']}/{s['out']}토큰 ({s['model']})")
        asyncio.run(run())
    write_outputs(points, raw, out_dir, args.seed)
    done = [raw[p["id"]] for p in points if raw.get(p["id"])]
    print(f"저장: {out_dir / 'p16_3_blind.md'} · {out_dir / 'p16_3_key.md'} — {len(done)}개 지점 · 합계 ${sum(d['H']['usd'] + d['S']['usd'] for d in done):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
