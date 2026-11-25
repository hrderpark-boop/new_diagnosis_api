#!/usr/bin/env python3
"""(2026-11-23 P16-0) 질문 생성 방식 비교 실험 — 제품 코드는 읽기만 한다(대화 엔진을 고치지 않는다).

11/23 운영(55415bc) Lucas 일관리·자기관리 실세션: 메아리는 사라졌지만 답에 대한 반응이 없고, 사실 하나만 묻는 좁은 질문이 많고,
수준을 가르는 것(결과의 크기, 팀의 방식으로 남았는지)을 묻지 않았다. 규칙을 더 얹지 않고 질문을 만드는 방식 자체를 바꿀지
사용자가 직접 읽고 고르게 하려고, 같은 지점에서 세 후보를 나란히 만든다.

  A  실제로 나온 코치 턴(전문에서 그대로 — 호출 없음). 사례를 닫고 다음 질문으로 넘어간 지점은 그렇게 표시한다.
  B  새 방식, 지금 대화 모델(Haiku) 호출 1회.
  C  새 방식, Sonnet 호출 1회(지시문은 B 와 같다).

새 방식의 입력: 영역 정의 · 지금 다루는 하위역량 · 그 하위역량의 수준 기준(Lv.1~4)과 Lv.3/Lv.4 를 가르는 조건 ·
이 사례의 대화 전체 · 이 영역에서 코치가 이미 한 말 · 코치 말투. 지시는 원칙만 적는다(예시 문장 없음).
겉모양 검사(어절 수·낱말 겹침)는 걸지 않고 말투 검사만 기록한다.

사용(워크트리 루트에서):
    .venv/bin/python tools/p16_compare.py --transcript ../sim/real_20261123_lucas.md --dry-run        # 지점을 찾고 지시문만 출력(호출 없음)
    .venv/bin/python tools/p16_compare.py --transcript ../sim/real_20261123_lucas.md --only 1         # 1개 지점만(턴당 비용·지연 확인)
    .venv/bin/python tools/p16_compare.py --transcript ../sim/real_20261123_lucas.md                  # 12개 지점 전부(이미 돌린 지점은 다시 부르지 않는다)

(2026-11-25 P16-2 0단계) 다른 실세션 전문에서도 돌릴 수 있게 했다 — 지점을 손으로 적지 않고 전문에서 찾는다(--auto 영역 키).
  사례 안에서 리더가 답한 자리 가운데 실제 코치 턴이 사례 중간 턴이거나 마무리 턴이었던 곳 전부. Sonnet(C)은 부르지 않는다(--no-sonnet).
    .venv/bin/python tools/p16_compare.py --transcript ../sim/real_20261125_lucas_org.md --auto organization_management --no-sonnet --tag p16_2 --dry-run
    .venv/bin/python tools/p16_compare.py --transcript ../sim/real_20261125_lucas_org.md --auto organization_management --no-sonnet --tag p16_2
  출력: <tag>_side_by_side.md(지점마다 리더 답 · 실제 코치 턴 · B) · <tag>_raw.json

(2026-11-25 P16-2 판정) 확인 1 — 실세션의 같은 자리에서 '수정한 운영 경로'의 코치 턴 생성 부분(services/coach_v2.render)을 그대로 돌린다(--replay).
  상태는 실세션 흐름을 따른다: 그 사례에서 이미 물은 것(팀의 방식·팀 밖)과 중간 턴 순번은 실세션의 실제 턴으로 세고, 마무리 턴 자리는 마무리 턴으로 부른다.
  닫기 제안은 꼬리 답이 둘 이상인 자리에서만 길을 열어 준다(칸 상태는 전문에 없어 행동 칸은 찼다고 본다). 라포 3턴과 영역 정의 받는 말 1턴도 같은 함수로 만든다.
    .venv/bin/python tools/p16_compare.py --transcript ../sim/real_20261125_lucas_org.md --auto organization_management --replay --tag p16_2b
  출력: <tag>_replay.md(지점마다 리더 답 · 11/25 실제 턴 · 이번 턴) · <tag>_replay_raw.json

출력(--out, 기본 전문과 같은 폴더):
    p16_compare_blind.md   지점마다 리더 답(앞 60자)과 후보 셋을 가/나/다로 — 지점마다 순서를 섞는다. 어느 것이 A/B/C 인지는 적지 않는다.
    p16_compare_key.md     정답표와 B·C 의 턴당 비용·지연.
    p16_compare_raw.json   지점별 원자료(지시문·출력·토큰·시간) — 다시 돌릴 때 이미 있는 지점은 건너뛴다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

COACH = "Lucas"
# 지점 12곳 — (영역 키, 리더 답의 끝부분). 이 답 바로 뒤의 코치 턴이 비교 대상이다.
POINTS: tuple[tuple[str, str], ...] = (
    ("work_management", "업무 순서를 다시 조정했습니다"),
    ("work_management", "저는 강사 섭외와 전체 교육 일정 조율을 맡았습니다"),
    ("work_management", "하루 이틀 정도 여유를 확보할 수 있었습니다"),
    ("work_management", "세부 자료 제작을 재개했습니다"),
    ("work_management", "응답 결과가 자동 집계되도록 절차를 개선했습니다"),
    ("work_management", "명확하게 표시해 응답하기 쉽게 수정했습니다"),
    ("work_management", "구체적인 개선 의견을 자발적으로 남겨주었습니다"),
    ("self_management", "라고 시작했습니다"),
    ("self_management", "회의 방식이 자리 잡고 있다고 느꼈습니다"),
    ("self_management", "학습 분량을 조정해 다음 교육과정에서 다시 시도했습니다"),
    ("self_management", "개선 효과가 있었다고 판단했습니다"),
    ("self_management", "대체 강사를 알아보는 것이 현실적이겠다고 판단했습니다"),
)
# 8번 지점은 끝부분이 짧아 앞의 인용까지 함께 본다
POINT_EXTRA: dict[int, str] = {8: "다른 대안이 있으면 함께 이야기해 봅시다"}

COACH_LABELS = ("코치", "coach", "lucas", "루카스", "ai", "assistant", "model", "c")
LEADER_LABELS = ("리더", "leader", "user", "사용자", "나", "참여자", "박기진", "l")
_SPEAKER_RE = re.compile(r"^\s*(?:[-*>#]+\s*)?(?:\*\*|\[)?\s*([A-Za-z가-힣]+)\s*(?:\([^)]*\))?\s*(?:\*\*|\])?\s*(?:\d+\s*)?[:：]\s*(.*)$")


def _norm(s: str) -> str:
    return re.sub(r"[\s\"“”'‘’…·.,!?~*_`>-]+", "", s or "")


def parse_transcript(text: str) -> list[tuple[str, str]]:
    """전문을 [(역할, 글)] 로 — 줄 머리의 말하는 이 표지('코치:', '**리더**:', 'Lucas:', '[사용자]:')로 가른다. 표지 없는 줄은 앞 턴에 잇는다."""
    turns: list[list[str]] = []
    for raw in text.splitlines():
        m = _SPEAKER_RE.match(raw)
        role = None
        if m:
            tag = m.group(1).strip().lower()
            role = "model" if tag in COACH_LABELS else ("user" if tag in LEADER_LABELS else None)
        if role:
            turns.append([role, m.group(2).strip()])
        elif turns and raw.strip() and not raw.lstrip().startswith(("#", "---")):
            turns[-1][1] = (turns[-1][1] + " " + raw.strip()).strip()
    return [(r, t) for r, t in turns if t]


def find_point(turns: list[tuple[str, str]], tail: str, extra: str | None, start: int = 0) -> int | None:
    """리더 답의 끝부분(tail)이 들어 있는 리더 턴의 자리. 끝에 가까운 턴을 먼저 본다(같은 말이 답 가운데에도 나올 수 있다)."""
    key, ex = _norm(tail), _norm(extra or "")
    hits = [i for i, (r, t) in enumerate(turns) if i >= start and r == "user" and key in _norm(t) and (not ex or ex in _norm(t))]
    ends = [i for i in hits if _norm(turns[i][1]).endswith(key)]
    return (ends or hits or [None])[0]


def anchor_subs(chapter: str) -> dict[str, list[str]]:
    """그 영역 하위역량의 여는 질문 사전 문안 — {하위역량 키: [문안, …]}."""
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK, SUBCOMPETENCY_ANCHOR_QUESTIONS
    return {k: list(SUBCOMPETENCY_ANCHOR_QUESTIONS.get(k, [])) for k in (COMPETENCY_FRAMEWORK[chapter]["indicators"] or {})}


def _keys(s: str) -> set[str]:
    return {w[:2] for w in re.split(r"[\s,.!?'\"“”‘’…]+", s or "") if len(w) >= 2}


def opener_sub(coach_text: str, chapter: str) -> str | None:
    """코치 턴이 그 영역 하위역량의 여는 질문이면 그 하위역량 키 — 사전 문안과 낱말이 60% 이상 겹칠 때(코치마다 끝맺음만 다르다)."""
    best, best_sub = 0.0, None
    sents = [x for x in re.split(r"(?<=[.?!])\s+", coach_text or "") if x.strip()]
    for sub, qs in anchor_subs(chapter).items():
        for q in qs:
            a = _keys(q)
            for s in sents[-2:]:
                b = _keys(s)
                if a and len(a & b) / len(a) > best:
                    best, best_sub = len(a & b) / len(a), sub
    return best_sub if best >= 0.6 else None


def chapter_start(turns: list[tuple[str, str]], chapter: str) -> int:
    """그 영역이 시작되는 코치 턴의 자리 — 영역 이름을 따옴표로 묻는 턴('일관리'를 … 어떻게 …)."""
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK
    name = COMPETENCY_FRAMEWORK[chapter]["name"]
    for i, (r, t) in enumerate(turns):
        if r == "model" and re.search(rf"['‘\"“]{name}['’\"”]", t):
            return i
    return 0


def level_block(chapter: str, sub: str | None) -> str:
    """수준 기준 — 그 하위역량의 Lv.1~4 서술과 행동 예시(data/competencies.py), Lv.3/Lv.4 를 가르는 판정 규칙(services/level_gate.py 규칙 3·6·9)."""
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK
    inds = COMPETENCY_FRAMEWORK[chapter]["indicators"]
    subs = [sub] if sub in inds else list(inds)
    out = []
    for k in subs:
        ind = inds[k]
        out.append(f"[{ind['name']}]")
        for lv in (1, 2, 3, 4):
            ex = " / ".join(x.strip("・ ").strip() for x in str((ind.get("examples") or {}).get(lv, "")).split("\n") if x.strip())
            out.append(f"  Lv.{lv}: {ind['levels'][lv]}" + (f" (예: {ex})" if ex else ""))
    out.append("[수준을 가르는 조건]")
    out.append("  - 리더가 실제로 한 구체 행동(때·상황·한 일)이어야 근거가 된다. 태도·일반론·'그런 일 없다'는 근거가 아니다.")
    out.append("  - Lv.2 와 Lv.3: 기존 기준을 따라 점검·공유만 했으면 Lv.2. 리더가 기준·틀·지표·절차를 직접 제안했고 그것이 팀의 합의·운영 방식이 됐으면 Lv.3.")
    out.append("  - Lv.3 과 Lv.4: Lv.4 는 행동의 범위가 팀 밖(타 부서·다른 팀·전사·외부 기관)일 때만. 팀 안에서 만든 장치는 아무리 정착했어도 Lv.3 이 상한.")
    out.append("  - 어느 수준이든 그 수준의 핵심 행동이 발화에 실제로 있어야 한다. 하나라도 빠지면 한 단계 아래로 본다.")
    return "\n".join(out)


def build_system() -> str:
    """새 방식의 지시 — 원칙만 적는다(예시 문장 없음)."""
    from diag_project.services.persona_register import register_hint
    return (
        "당신은 경험 많은 역량 면접관입니다. 목적은 이 사례에서 리더가 실제로 한 행동·판단·결과를 수준을 가릴 수 있을 만큼 듣는 것입니다.\n\n"
        "[출력]\n"
        "- (선택) 반응 한 문장 + 질문 하나. 또는 더 물을 것이 없으면 '[닫음]'이라고 쓰고 이유를 한 줄로 적는다.\n"
        "- 그 밖의 설명·머리말·번호는 쓰지 않는다.\n\n"
        "[반응]\n"
        "- 리더의 답을 되풀이하지 않는다. 답의 뜻을 한마디로 짚거나 상황의 어려움을 알아준다.\n"
        "- 칭찬과 평가는 하지 않는다.\n"
        "- 자연스러울 때만 붙인다. 앞 턴들과 같은 꼴을 피한다.\n\n"
        "[질문 고르기]\n"
        "- 지금까지 들은 것 가운데 가장 덜 드러난 것 하나를 묻는다 — 리더 본인의 구체 행동, 그렇게 판단한 까닭, 결과의 크기, 팀원에게 어떻게 했는지, "
        "그 방식이 이후 팀에 남았는지, 사례가 어떻게 끝났는지.\n"
        # (2026-11-23 검토자 추가) 수준 판정 규칙 6·9 에 맞춘 한 줄 — Lv.3 은 팀의 운영 방식이 됐는가, Lv.4 는 팀 밖으로 이어졌는가
        "- 그 방식이 팀의 운영 방식이 됐는지, 팀 밖(다른 부서·전사·외부)으로 이어졌는지.\n\n"
        "[질문 꼴]\n"
        "- 이야기를 청하는 열린 질문을 먼저 쓴다. 사실 하나만 묻는 질문은 꼭 필요할 때만 쓴다.\n"
        "- 예·아니오로 답할 수 있는 질문은 쓰지 않는다. 한 번에 하나만 묻는다.\n\n"
        "[금지]\n"
        "- 이미 답한 것을 다시 묻기, 리더가 하지 않은 말을 전제로 삼기, 일어나지 않은 일을 가정해 묻기, 다른 사람의 속마음을 묻기.\n\n"
        f"[말투] 코치 {COACH} — {register_hint(COACH)} 리더를 부를 때는 '리더님'이라고만 한다."
    )


def build_user(*, chapter: str, sub: str | None, case: list[tuple[str, str]], coach_said: list[str]) -> str:
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK
    comp = COMPETENCY_FRAMEWORK[chapter]
    sub_name = comp["indicators"][sub]["name"] if sub in comp["indicators"] else "(여는 질문에서 가려내지 못함 — 이 영역의 하위역량 전체를 참고)"
    convo = "\n".join(f"{'코치' if r == 'model' else '리더'}: {t}" for r, t in case)
    said = "\n".join(f"- {t}" for t in coach_said) or "- (없음)"
    return (
        f"[영역] {comp['name']} — {comp['description']}\n"
        f"[지금 다루는 하위역량] {sub_name}\n\n"
        f"[수준 기준]\n{level_block(chapter, sub)}\n\n"
        f"[이 영역에서 코치가 이미 한 말]\n{said}\n\n"
        f"[이 사례의 대화 — 마지막 줄이 리더가 방금 한 답]\n{convo}\n\n"
        "이제 코치가 할 말을 씁니다."
    )


def locate(turns: list[tuple[str, str]]) -> list[dict]:
    """지점 12곳의 자리와 재료 — 리더 답, 실제 코치 턴(A), 이 사례의 대화, 이 영역에서 코치가 이미 한 말, 하위역량."""
    out = []
    starts = {ch: chapter_start(turns, ch) for ch in {c for c, _t in POINTS}}
    for n, (chapter, tail) in enumerate(POINTS, 1):
        i = find_point(turns, tail, POINT_EXTRA.get(n), start=starts[chapter])
        if i is None:
            out.append({"n": n, "chapter": chapter, "tail": tail, "found": False})
            continue
        ch0 = starts[chapter]
        # 이 사례를 연 코치 턴 — 지점 앞에서 가장 가까운 여는 질문
        open_i, sub = ch0, None
        for j in range(i - 1, ch0 - 1, -1):
            if turns[j][0] == "model":
                s = opener_sub(turns[j][1], chapter)
                if s:
                    open_i, sub = j, s
                    break
        actual = next((t for r, t in turns[i + 1:i + 2] if r == "model"), "")
        nxt_sub = opener_sub(actual, chapter) if actual else None
        # 사례를 닫은 꼴 — 다음 사례의 여는 질문으로 넘어갔거나(next), 질문 없이 영역을 마무리하는 요약으로 넘어갔다(end)
        closed = "next" if nxt_sub else ("end" if (not actual or "?" not in actual) else "")
        out.append({"n": n, "chapter": chapter, "tail": tail, "found": True, "leader": turns[i][1], "actual": actual,
                    "actual_closed": closed, "sub": sub, "case": turns[open_i:i + 1],
                    "coach_said": [t for r, t in turns[ch0:i] if r == "model"], "turn_index": i})
    return out


_WRAP_MARK_RE = re.compile(r"이해했습니다|이해했어요|(하나|한\s*가지)만\s*(더\s*)?(확인|여쭙|여쭤)")


def locate_auto(turns: list[tuple[str, str]], chapter: str) -> list[dict]:
    """(P16-2) 그 영역의 사례 안에서 리더가 답한 자리 전부 — 바로 뒤의 실제 코치 턴이 사례 중간 턴(mid)이거나 마무리 턴(wrap)인 곳.
    뒤의 코치 턴이 다음 사례의 여는 질문이거나 영역 요약이면 뺀다(그 답은 마무리 질문의 답이다). 앞 답과 글자가 같은 답(같은 답 반복 처리 턴)도 뺀다."""
    ch0 = chapter_start(turns, chapter)
    out: list[dict] = []
    open_i, sub, prev_leader = None, None, ""
    for i in range(ch0, len(turns)):
        r, t = turns[i]
        if r == "model":
            s_ = opener_sub(t, chapter)
            if s_:
                open_i, sub = i, s_
            continue
        if open_i is None:
            continue
        actual = next((x for rr, x in turns[i + 1:i + 2] if rr == "model"), "")
        same = _norm(t) == _norm(prev_leader)
        prev_leader = t
        # 영역 요약(전문의 마지막 코치 턴 — 물음 없이 다음 영역을 알린다)과 다음 사례의 여는 질문은 뺀다. 물음표 없는 꼬리 질문('…궁금합니다.')은 넣는다
        is_end = (i + 2 >= len(turns)) and "?" not in actual
        if not actual or is_end or opener_sub(actual, chapter) or same:
            continue
        out.append({"n": len(out) + 1, "chapter": chapter, "tail": t[-20:], "found": True, "leader": t, "actual": actual,
                    "actual_closed": "", "kind": "wrap" if _WRAP_MARK_RE.search(actual) else "mid", "sub": sub,
                    "case": turns[open_i:i + 1], "coach_said": [x for rr, x in turns[ch0:i] if rr == "model"], "turn_index": i})
    return out


def write_side_by_side(points: list[dict], raw: dict, out_dir: Path, tag: str, title: str) -> Path:
    """(P16-2) 가리지 않고 나란히 — 지점마다 리더 답 전체 · 실제로 나간 코치 턴 · B(새 방식, Haiku)."""
    L = [f"# {title}", "", "지점마다 리더가 방금 한 답, 실제로 나간 코치 턴, 같은 자리에서 P16-0 비교 도구의 새 방식(B, Haiku)이 쓴 턴입니다.",
         "B 의 입력은 P16-0 그대로입니다(영역 정의·하위역량·수준 기준·이 영역에서 코치가 한 말 전부·이 사례의 대화). 겉모양 검사·다시 쓰기는 없습니다.", ""]
    for p in points:
        r = raw.get(str(p["n"]))
        if not r:
            continue
        L += [f"## 지점 {p['n']} — 실제 턴: {'사례 마무리 턴' if p.get('kind') == 'wrap' else '사례 중간 턴'}", "",
              f"- 리더: {p['leader']}", f"- **실제**: {p['actual']}", f"- **B**: {r['B']['text']}", ""]
    done = [raw[str(p["n"])] for p in points if raw.get(str(p["n"]))]
    if done:
        usd = [d["B"]["usd"] for d in done]
        sec = sorted(d["B"]["sec"] for d in done)
        L += [f"B(Haiku) {len(done)}개 지점 — 비용 합계 ${sum(usd):.4f} · 지연 중앙 {sec[len(sec) // 2]}초 · 최대 {sec[-1]}초"]
    path = out_dir / f"{tag}_side_by_side.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return path


def _meter_total() -> tuple[float, int]:
    """지금까지의 호출 비용(USD)과 호출 수 — 호출 종류를 가리지 않고 합친다."""
    from diag_project.llm_service import USAGE_METER, _PRICE
    usd, n = 0.0, 0
    for (_c, m), d in USAGE_METER.by_type.items():
        pr = _PRICE.get(m, {"in": 0.0, "out": 0.0})
        usd += (int(d["input"]) * pr["in"] + (int(d["output"]) + int(d["thoughts"])) * pr["out"]) / 1e6
        n += int(d.get("calls") or 0)
    return usd, n


def replay_early(turns: list[tuple[str, str]], chapter: str) -> list[dict]:
    """(P16-2 판정) 라포 3턴 — 새 방식이 켜진 턴 핸들러가 쓰는 함수 그대로(호출 없음). 되물음·다음 질문은 고정 문구라 실세션의 것을 그대로 둔다."""
    from diag_project.services.input_anomaly import is_bare_noun_list, is_contentless_smalltalk
    from diag_project.services.intro_messages import persona_line, rapport_counter_reply, rapport_fixed_receive, role_fixed_receive
    from diag_project.services.output_guard import is_question, split_sentences
    from diag_project.services.turn_checks import is_counter_question
    ch0 = chapter_start(turns, chapter)
    users = [i for i in range(ch0) if turns[i][0] == "user"]
    out, prev_new = [], ""
    for n, i in enumerate(users[1:4], 1):          # 이름 답 다음의 세 답 — 스몰톡 · 스몰톡 되물음의 답 · 맡은 일
        ans, actual = turns[i][1], (turns[i + 1][1] if i + 1 < len(turns) else "")
        fixed_q = next((x.strip() for x in reversed(split_sentences(actual)) if x.strip() and is_question(x)), "")
        if n == 3:
            new, how = (f"{role_fixed_receive(COACH)} {persona_line(COACH, 'expect_q')}", "맡은 일 답(낱말 나열) — 고정 받기") if is_bare_noun_list(ans) else ("", "LLM 받기(이 도구에서는 만들지 않음)")
        elif is_counter_question(ans):
            new, how = f"{rapport_counter_reply(COACH)} {fixed_q}", "되물음에 한 문장으로 답함"
        elif is_contentless_smalltalk(ans):
            new, how = f"{rapport_fixed_receive(COACH, prev_new or turns[i - 1][1], start=n - 1)} {fixed_q}", "짧은 답 — 고정 받기(리더 말을 옮기는 호출을 부르지 않음)"
        else:
            new, how = "", "LLM 받기(이 도구에서는 만들지 않음)"
        prev_new = new
        out.append({"label": f"라포 {n}", "leader": ans, "actual": actual, "new": new, "how": how})
    return out


async def replay_early_s(llm, turns: list[tuple[str, str]], chapter: str) -> list[dict]:
    """(P16-4) 라포 3턴 — Sonnet 이 받는 말을 쓰고(coach_v2.render_receive_s) 정해진 다음 질문이 붙는다. 다음 질문은 실세션의 것을 그대로 둔다."""
    from diag_project.services import coach_v2 as V
    from diag_project.services.output_guard import is_question, split_sentences
    ch0 = chapter_start(turns, chapter)
    users = [i for i in range(ch0) if turns[i][0] == "user"]
    out = []
    for n, i in enumerate(users[1:4], 1):
        actual = turns[i + 1][1]
        ss = [x.strip() for x in split_sentences(actual) if x.strip()]
        k = next((j for j, x in enumerate(ss) if is_question(x)), len(ss) - 1)
        next_q, tr = " ".join(ss[k:]), []
        txt, how = await V.render_receive_s(llm, kind="rapport", history=turns[:i + 1], persona_name=COACH, next_q=next_q, trace=tr)
        out.append({"label": f"라포 {n}", "leader": turns[i][1], "actual": actual, "new": (f"{txt} {next_q}" if txt else ""),
                    "how": f"Sonnet 받는 말({how}) + 정해진 다음 질문" + ("" if txt else " — 떨어져 종전 길로 감"), "drops": tr})
    return out


async def replay(llm, turns: list[tuple[str, str]], chapter: str, points: list[dict], sonnet: bool = False) -> tuple[list[dict], dict]:
    """(P16-2 판정) 영역 정의 받는 말 1턴 + 사례 안 13곳 — services/coach_v2 의 호출을 그대로 부른다. (결과 목록, 영역 정의 턴).
    sonnet — (P16-4) 코치의 말을 Sonnet 이 쓰는 경로(render_s · render_receive_s)로 돌린다."""
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK
    from diag_project.services import coach_v2 as V
    from diag_project.services.intro_messages import align_fixed_receive
    from diag_project.services.output_guard import split_sentences
    ch0 = chapter_start(turns, chapter)
    d_ans = next((turns[i][1] for i in range(ch0 + 1, len(turns)) if turns[i][0] == "user"), "")
    d_actual = next((turns[i][1] for i in range(ch0 + 1, len(turns)) if turns[i][0] == "model"), "")
    tr_a: list = []
    if sonnet:
        d_q = next((turns[i][1] for i in range(ch0, len(turns)) if turns[i][0] == "model"), "")
        g_txt, g_how = await V.render_receive_s(llm, kind="align", history=[("model", d_q), ("user", d_ans)], persona_name=COACH, trace=tr_a)
        g_how = f"Sonnet({g_how})"
    else:
        g_txt, g_how = await V.render_align_gist(llm, leader_answer=d_ans, persona_name=COACH, trace=tr_a)
    align = {"label": "영역 정의 받는 말", "leader": d_ans, "actual": next((x.strip() for x in split_sentences(d_actual) if x.strip()), ""),
             "new": g_txt or align_fixed_receive(COACH, 0), "how": g_how + ("" if g_txt else " → 고정 받기"), "drops": tr_a}
    inds = COMPETENCY_FRAMEWORK[chapter]["indicators"]
    out: list[dict] = []
    prev_open, asked, mid_n, beyond_n = None, set(), 0, 0
    for p in points:
        if p["case"][0][1] != prev_open:
            prev_open, asked, mid_n = p["case"][0][1], set(), 0
        tail = sum(1 for r, _t in p["case"] if r == "user") - 1
        meta, tr = {}, []
        kw = dict(chapter=chapter, sub_name=(inds[p["sub"]]["name"] if p["sub"] in inds else None), case=p["case"], coach_said=p["coach_said"],
                  persona_name=COACH, trace=tr, meta=meta, mid_n=mid_n, asked=sorted(asked))
        t0 = time.perf_counter()
        if sonnet:
            kw_s = {k: v for k, v in kw.items() if k != "mid_n"}
            text, how = await V.render_s(llm, mode=p["kind"], can_close=(p["kind"] == "mid" and tail >= V.CLOSE_MIN_TAIL_ANSWERS), **kw_s)
        elif p["kind"] == "mid":
            text, how = await V.render(llm, mode="mid", can_close=tail >= V.CLOSE_MIN_TAIL_ANSWERS, **kw)
        else:
            text, how = await V.render(llm, mode="wrap", missing=[], result_filled=True, beyond_n=beyond_n, **kw)
        out.append({"n": p["n"], "kind": p["kind"], "leader": p["leader"], "actual": p["actual"], "new": text, "how": how, "meta": meta, "drops": tr,
                    "sec": round(time.perf_counter() - t0, 2), "tail": tail, "asked_before": sorted(asked), "can_close": p["kind"] == "mid" and tail >= V.CLOSE_MIN_TAIL_ANSWERS})
        # 상태는 실세션 흐름을 따른다 — 실제로 나간 턴이 물은 것과 순번으로 다음 자리의 상태를 정한다
        kinds = V.asked_kinds(p["actual"])
        asked |= kinds
        if p["kind"] == "mid":
            mid_n += 1
        elif "beyond" in kinds:
            beyond_n += 1
    return out, align


def write_replay(early: list[dict], align: dict, rows: list[dict], out_dir: Path, tag: str, usd: float, calls: int) -> Path:
    how_ko = {"close": "닫음 — 모델이 더 물을 것이 없다고 냄(상태 기계가 받아 마무리 단계로 넘긴다)", "skip:none_left": "마무리 턴 없음 — 물을 것이 남지 않음(넘김말로 바로 다음 주제)",
              "miss:again": "마무리 턴 없음 — 이미 물은 것을 다시 물어 버림(넘김말로 바로 다음 주제)", "miss:beyond": "마무리 턴 없음 — 영역당 횟수를 채운 팀 밖 물음이라 버림"}
    L = ["# P16-2 판정 · 확인 1 — 실세션 답으로 다시 돌리기", "",
         "지점마다 리더가 한 답, 11/25 에 실제로 나간 코치 턴, 수정한 운영 경로(coach_v2)가 같은 자리에서 쓴 턴입니다.",
         "상태는 실세션 흐름을 따릅니다 — 그 사례에서 이미 물은 것과 중간 턴 순번은 11/25 의 실제 턴으로 셉니다. 닫기 제안은 꼬리 답이 둘 이상인 자리에서만 길을 열었습니다.", ""]
    for e in early + [align]:
        L += [f"## {e['label']}", "", f"- 리더: {e['leader']}", f"- **11/25 실제**: {e['actual']}", f"- **이번**: {e['new'] or '(없음)'}", f"- 만든 방식: {e['how']}", ""]
    for r in rows:
        note = ("마무리 턴 없음 — 모델이 물을 것이 없다고 냄(넘김말로 바로 다음 주제)" if (r["how"] == "close" and r["kind"] == "wrap") else how_ko.get(r["how"], ""))
        m = r["meta"]
        tags = [x for x in (f"다시 씀({m['rewrite']})" if m.get("rewrite") else "", f"앞 절 뗌({m['front_cut']})" if m.get("front_cut") else "",
                            f"평서문 {m['stmt_cut']}개 지움" if m.get("stmt_cut") else "", f"이해 확인 뺌({m['sum_drop']})" if m.get("sum_drop") else "",
                            f"이해 확인 {m['sum_eojeol']}어절" if m.get("sum_eojeol") and not m.get("sum_drop") else "", f"남은 꼴({m['left']})" if m.get("left") else "",
                            f"대상 {m['target']}" if m.get("target") else "", "닫기 길 열림" if r["can_close"] else "",
                            f"닫음 이유(기록에만): {m['close_reason']}" if m.get("close_reason") else "", f"{r['sec']}초") if x]
        L += [f"## 지점 {r['n']} — {'사례 마무리 턴 자리' if r['kind'] == 'wrap' else '사례 중간 턴'} (이 사례의 꼬리 답 {r['tail']}개째 뒤"
              + (f", 이미 물은 것: {'·'.join(r['asked_before'])}" if r["asked_before"] else "") + ")", "",
              f"- 리더: {r['leader']}", f"- **11/25 실제**: {r['actual']}", f"- **이번**: {r['new'] or '[' + (note or r['how']) + ']'}", f"- 기록: {' · '.join(tags)}", ""]
    L += [f"호출 {calls}회 · 비용 ${usd:.4f}"]
    path = out_dir / f"{tag}_replay.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return path


async def call(llm, *, system: str, user: str, sonnet: bool) -> dict:
    from diag_project.llm_service import ANALYSIS_MODEL, USAGE_METER, _PRICE
    ct = "p16_compare_sonnet" if sonnet else "p16_compare_haiku"
    before = {k: dict(v) for k, v in USAGE_METER.by_type.items() if k[0] == ct}
    t0 = time.perf_counter()
    text = await llm._generate_with_retry(prompt=user, system_instruction=system, max_tokens=400, thinking_budget=0, call_type=ct,
                                          model=(ANALYSIS_MODEL if sonnet else None), temperature=0.4)
    sec = round(time.perf_counter() - t0, 2)
    tok_in = tok_out = 0
    model = ""
    for (c, m), d in USAGE_METER.by_type.items():
        if c != ct:
            continue
        b = before.get((c, m), {})
        tok_in += int(d["input"]) - int(b.get("input", 0))
        tok_out += int(d["output"]) + int(d["thoughts"]) - int(b.get("output", 0)) - int(b.get("thoughts", 0))
        model = m
    pr = _PRICE.get(model, {"in": 0.0, "out": 0.0})
    return {"text": (text or "").strip(), "sec": sec, "in": tok_in, "out": tok_out, "model": model,
            "usd": round((tok_in * pr["in"] + tok_out * pr["out"]) / 1e6, 6)}


def register_note(text: str) -> list[str]:
    from diag_project.services.persona_register import register_violations
    return register_violations(COACH, text, scope="all")


def write_outputs(points: list[dict], raw: dict, out_dir: Path, seed: int) -> None:
    rng = random.Random(seed)
    L = ["# P16-0 질문 생성 방식 비교 — 가림 판", "",
         "지점마다 리더가 방금 한 답(앞 60자)과 코치 턴 후보 셋입니다. 순서는 지점마다 섞었고, 어느 방식인지는 적지 않았습니다.", ""]
    K = ["# P16-0 질문 생성 방식 비교 — 정답표", "", "A = 실제로 나온 코치 턴 · B = 새 방식(Haiku) · C = 새 방식(Sonnet)", "",
         "| 지점 | 가 | 나 | 다 | B 비용(USD) | B 지연(초) | C 비용(USD) | C 지연(초) |", "|---|---|---|---|---|---|---|---|"]
    names = {"work_management": "일관리", "self_management": "자기관리"}
    for p in points:
        r = raw.get(str(p["n"]))
        if not p.get("found") or not r:
            continue
        a_text = p["actual"] or "(코치 턴 없음)"
        if p.get("actual_closed") == "next":
            a_text += "  ← (이 사례를 닫고 다음 질문으로 넘어감)"
        elif p.get("actual_closed") == "end":
            # 영역 종료 요약은 길다 — 첫 문장만 싣는다
            first = re.split(r"(?<=[.?!])\s+", a_text)[0]
            a_text = f"{first} …(이하 영역 종료 요약)  ← (이 사례를 닫고 영역을 마무리함)"
        cands = [("A", a_text), ("B", r["B"]["text"]), ("C", r["C"]["text"])]
        rng.shuffle(cands)
        L.append(f"## 지점 {p['n']} — {names[p['chapter']]}")
        L.append(f"리더: {p['leader'][:60]}…" if len(p["leader"]) > 60 else f"리더: {p['leader']}")
        L.append("")
        for lab, (_k, t) in zip("가나다", cands):
            L.append(f"- **{lab}**: {t}")
        L.append("")
        K.append(f"| {p['n']} | " + " | ".join(k for k, _t in cands)
                 + f" | {r['B']['usd']:.5f} | {r['B']['sec']} | {r['C']['usd']:.5f} | {r['C']['sec']} |")
    done = [raw[str(p["n"])] for p in points if raw.get(str(p["n"]))]
    if done:
        for tag, name in (("B", "Haiku"), ("C", "Sonnet")):
            usd = [d[tag]["usd"] for d in done]
            sec = sorted(d[tag]["sec"] for d in done)
            K += ["", f"{tag}({name}) — 턴당 비용 평균 ${sum(usd) / len(usd):.5f} · 지연 중앙 {sec[len(sec) // 2]}초 · 최대 {sec[-1]}초 · "
                      f"입력 토큰 평균 {sum(d[tag]['in'] for d in done) // len(done)} · 출력 토큰 평균 {sum(d[tag]['out'] for d in done) // len(done)} · "
                      f"세션 150턴 환산 ${150 * sum(usd) / len(usd):.2f}"]
        K += ["", f"실제 비용 합계: ${sum(d['B']['usd'] + d['C']['usd'] for d in done):.4f} ({len(done)}개 지점)"]
        notes = [f"지점 {p['n']} {tag}: {v}" for p in points if raw.get(str(p["n"])) for tag in ("B", "C") for v in raw[str(p["n"])][tag].get("register", [])]
        K += ["", "말투 검사에 걸린 문장: " + (" / ".join(notes) if notes else "없음")]
    (out_dir / "p16_compare_blind.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (out_dir / "p16_compare_key.md").write_text("\n".join(K) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="P16-0 질문 생성 방식 비교(제품 코드 수정 없음)")
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", type=int, default=0, help="앞에서 이만큼의 지점만 돌린다(0 = 전부)")
    ap.add_argument("--dry-run", action="store_true", help="지점을 찾고 지시문만 출력한다(LLM 호출 없음)")
    ap.add_argument("--seed", type=int, default=20261123)
    ap.add_argument("--auto", default=None, help="(P16-2) 영역 키 — 지점을 전문에서 찾는다(사례 안에서 리더가 답한 자리 전부)")
    ap.add_argument("--no-sonnet", action="store_true", help="(P16-2) Sonnet(C)은 부르지 않는다 — B(Haiku)만")
    ap.add_argument("--tag", default="p16_compare", help="(P16-2) --auto 출력 파일 이름의 머리")
    ap.add_argument("--replay", action="store_true", help="(P16-2 판정) --auto 지점에서 수정한 운영 경로(coach_v2)의 코치 턴 생성을 그대로 돌린다")
    ap.add_argument("--coach-model", default="", help="(P16-4) sonnet — 코치의 말을 Sonnet 이 쓰는 경로로 재실행한다")
    args = ap.parse_args(argv)
    path = Path(args.transcript)
    out_dir = Path(args.out) if args.out else path.parent
    turns = parse_transcript(path.read_text(encoding="utf-8"))
    points = locate_auto(turns, args.auto) if args.auto else locate(turns)
    print(f"전문 {len(turns)}턴(코치 {sum(1 for r, _t in turns if r == 'model')} · 리더 {sum(1 for r, _t in turns if r == 'user')})")
    for p in points:
        if not p.get("found"):
            print(f"지점 {p['n']}: 못 찾음 — '{p['tail']}'")
        else:
            print(f"지점 {p['n']}: 턴 {p['turn_index']} · 하위역량 {p['sub']} · 사례 {len(p['case'])}턴 · 실제 코치 턴{'(사례 닫음: ' + p['actual_closed'] + ')' if p['actual_closed'] else ''}"
                  f"{'[' + p['kind'] + ']' if p.get('kind') else ''}: {p['actual'][:60]}")
    if any(not p.get("found") for p in points):
        print("찾지 못한 지점이 있습니다 — 전문의 형식이나 끝부분 문구를 확인하세요.")
        return 2
    if args.replay:
        if not args.auto:
            print("--replay 는 --auto <영역 키>와 함께 쓴다.")
            return 2
        use_s = args.coach_model.strip().lower() == "sonnet"
        early = replay_early(turns, args.auto)
        if args.dry_run:
            for e in early:
                print(f"{e['label']}: {e['leader']} → {e['new']}  ({e['how']})")
            return 0
        from diag_project.llm_service import GeminiService
        llm_r = GeminiService().bind_provider("claude")
        usd0, n0 = _meter_total()
        if use_s:
            early = asyncio.run(replay_early_s(llm_r, turns, args.auto))
        rows, align = asyncio.run(replay(llm_r, turns, args.auto, points, sonnet=use_s))
        usd1, n1 = _meter_total()
        (out_dir / f"{args.tag}_replay_raw.json").write_text(json.dumps({"early": early, "align": align, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"저장: {write_replay(early, align, rows, out_dir, args.tag, usd1 - usd0, n1 - n0)} · 호출 {n1 - n0}회 · ${usd1 - usd0:.4f}")
        return 0
    system = build_system()
    if args.dry_run:
        p = points[0]
        print("\n===== 지시문(system) =====\n" + system)
        print("\n===== 입력(지점 1) =====\n" + build_user(chapter=p["chapter"], sub=p["sub"], case=p["case"], coach_said=p["coach_said"]))
        return 0
    raw_path = out_dir / (f"{args.tag}_raw.json" if args.auto else "p16_compare_raw.json")
    raw = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.exists() else {}
    from diag_project.llm_service import GeminiService
    llm = GeminiService().bind_provider("claude")

    async def run() -> None:
        for p in (points[:args.only] if args.only else points):
            if raw.get(str(p["n"])):
                continue
            user = build_user(chapter=p["chapter"], sub=p["sub"], case=p["case"], coach_said=p["coach_said"])
            b = await call(llm, system=system, user=user, sonnet=False)
            b["register"] = register_note(b["text"])
            if args.no_sonnet:
                raw[str(p["n"])] = {"B": b, "user_prompt": user}
                raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"지점 {p['n']}: B ${b['usd']:.5f} {b['sec']}초")
                continue
            c = await call(llm, system=system, user=user, sonnet=True)
            c["register"] = register_note(c["text"])
            raw[str(p["n"])] = {"B": b, "C": c, "user_prompt": user}
            raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"지점 {p['n']}: B ${b['usd']:.5f} {b['sec']}초 · C ${c['usd']:.5f} {c['sec']}초")
    asyncio.run(run())
    if args.auto:
        print(f"저장: {write_side_by_side(points, raw, out_dir, args.tag, 'P16-2 0단계 b) 실제 코치 턴과 P16-0 새 방식(B) 나란히 보기')}")
        return 0
    write_outputs(points, raw, out_dir, args.seed)
    print(f"저장: {out_dir / 'p16_compare_blind.md'} · {out_dir / 'p16_compare_key.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
