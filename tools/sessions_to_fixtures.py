"""운영 세션 전문(txt) → 리더 입력 fixture(json). (2026-10-29 P0 재생 입력)

전문 형식(채팅 화면 복사본):
  <코치이름>\n<코치 메시지 — 문단은 빈 줄로 구분, 각 문단은 한 줄>\n<리더 입력 줄(들)>\n\n\n<코치이름>\n...
리더 입력은 코치 마지막 문단(한 줄) 바로 뒤에 줄바꿈으로 이어진다. 오타·'sp'·'네?'·코치 질문 붙여넣기 전부 그대로 보존한다.
단, 프론트 버튼이 보내는 고정 문구(챕터 전환 '네, 다음으로 이어가 주세요.' / 일시정지 '괜찮아요, 계속 진행할게요.')는 재생 클라이언트가
같은 자리에서 자동으로 보내므로 fixture 에서 뺀다(뺀 수를 출력).

용법: python tools/sessions_to_fixtures.py tests/fixtures/sessions_1028
출력: 같은 폴더에 <coach>_users.json, 그리고 추출 요약(세그먼트 수·입력 수·의심 세그먼트).
"""
import json
import os
import re
import sys

COACHES = {"jessica": "제시카", "olivia": "올리비아", "daniel": "다니엘", "michael": "마이클", "lucas": "루카스"}
BUTTON_TEXTS = {"네, 다음으로 이어가 주세요.", "괜찮아요, 계속 진행할게요."}


def extract(txt: str, marker: str, pairs: list[dict] | None = None) -> tuple[list[str], list[dict]]:
    """pairs 에 {"coach": 직전 코치 발화 전문, "user": 리더 입력} 을 함께 모은다(누설 사전의 '인용' 판정용, 2026-10-29)."""
    segs = re.split(rf"(?:^|\n){re.escape(marker)}\n", "\n" + txt)
    inputs: list[str] = []
    notes: list[dict] = []
    for si, seg in enumerate(segs):
        seg = seg.strip("\n")
        if not seg.strip():
            continue
        paras = [p for p in re.split(r"\n\s*\n", seg) if p.strip()]
        last = paras[-1].split("\n")
        coach_line, leader_lines = last[0], [l for l in last[1:] if l.strip() != ""]
        if not leader_lines and len(paras) > 1 and not coach_line.strip().endswith("?"):
            # 리더가 빈 줄로 문단을 나눠 답한 경우(Olivia 전문): 마지막 '?' 로 끝나는 코치 질문 문단 뒤의 문단 전부가 리더 입력.
            #   코치 목록('· ')·고정 다리('먼저 … 쪽부터')가 섞이면 코치 본문이므로 입력 없음으로 둔다.
            qi = max((i for i, p in enumerate(paras[:-1]) if p.split("\n")[0].strip().endswith("?")), default=None)
            if qi is not None:
                q_lines = paras[qi].split("\n")
                cand = [l for l in q_lines[1:] if l.strip()] + ["\n".join(x for x in p.split("\n") if x.strip()) for p in paras[qi + 1:]]
                if cand and not any(l.lstrip().startswith("·") or "쪽부터" in l for l in cand):
                    coach_line, leader_lines = q_lines[0], cand
        if not leader_lines:
            notes.append({"seg": si, "kind": "입력 없음", "coach_tail": coach_line[-60:]})
            continue
        if not re.search(r"[?.!요다죠까]\s*$", coach_line.strip()):
            notes.append({"seg": si, "kind": "코치 줄 끝 모양 의심", "coach_tail": coach_line[-60:], "leader": leader_lines[0][:40]})
        text = "\n\n".join(leader_lines).strip() if any("\n" in l for l in leader_lines) else "\n".join(leader_lines).strip()
        if text in BUTTON_TEXTS:
            notes.append({"seg": si, "kind": "버튼 문구 제외", "leader": text})
            continue
        inputs.append(text)
        if pairs is not None:
            coach_text = "\n".join(l for p_ in paras for l in p_.split("\n") if l.strip() and l.strip() not in {x.strip() for x in leader_lines})
            pairs.append({"coach": coach_text, "user": text})
    return inputs, notes


def main(folder: str) -> int:
    for key, marker in COACHES.items():
        path = os.path.join(folder, f"{key}.txt")
        if not os.path.exists(path):
            print(f"!! {path} 없음")
            continue
        txt = open(path, encoding="utf-8").read()
        pairs: list[dict] = []
        inputs, notes = extract(txt, marker, pairs)
        out = os.path.join(folder, f"{key}_users.json")
        json.dump(inputs, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump(pairs, open(os.path.join(folder, f"{key}_pairs.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        n_btn = sum(1 for n in notes if n["kind"] == "버튼 문구 제외")
        n_sus = [n for n in notes if n["kind"] == "코치 줄 끝 모양 의심"]
        print(f"=== {key}: 코치 턴 {txt.count(marker + chr(10))} · 입력 {len(inputs)} · 버튼 제외 {n_btn} · 의심 {len(n_sus)} → {out}")
        for n in n_sus[:6]:
            print("   의심:", n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/sessions_1028"))
