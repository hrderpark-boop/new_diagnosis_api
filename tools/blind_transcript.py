"""(2026-10-29 P2-1) 블라인드 전문 — 코치 이름·어미를 가린 재생 전문을 무작위 순서(A~E)로 묶는다. 검토자는 질문 '내용'으로 코치를 맞힌다.

용법: python tools/blind_transcript.py OUT.md KEY.json replay_result_*.json
  - 코치 이름(영문·한글)·'코치' 호칭을 '●●' 로, 리더 이름을 '리더님' 으로
  - 문장 끝 어미(마지막 어절의 활용 부분)를 '~' 로 가린다: '있으셨습니까?' → '있으~?', '어땠어요?' → '어땠~?'
  - KEY.json 에 {라벨: 파일} 정답을 따로 쓴다(검토자에게는 OUT.md 만)
"""
import json
import random
import re
import sys

NAMES = {"2": "Jessica", "3": "Olivia", "4": "Daniel", "5": "Michael", "6": "Lucas", "1": "Ella"}
NAME_RE = re.compile(r"(Jessica|Olivia|Daniel|Michael|Lucas|Ella|제시카|올리비아|다니엘|마이클|루카스|엘라)(\s*코치)?")
# 어미 가림: 마지막 어절에서 어간 2글자 뒤를 '~' 로. 물음표·마침표 보존.
_END_RE = re.compile(r"([가-힣]{2})[가-힣]{1,6}([?.!])(\s|$)")


def mask(text: str) -> str:
    t = NAME_RE.sub("●●", text or "")
    t = re.sub(r"박기진|기진", "리더", t)
    t = _END_RE.sub(lambda m: f"{m.group(1)}~{m.group(2)}{m.group(3)}", t)
    return t


def main(out_md: str, key_json: str, files: list[str]) -> int:
    random.seed()
    order = list(files)
    random.shuffle(order)
    labels = [chr(ord("A") + i) for i in range(len(order))]
    key = {}
    parts = ["# 블라인드 전문 — 코치 이름·어미 가림\n", "질문의 '내용'(기준·대조·관찰·응원/실행 의지·한 줄 정리)으로 어느 코치인지 적어 주세요.\n"]
    for lab, f in zip(labels, order):
        d = json.load(open(f, encoding="utf-8"))
        key[lab] = {"file": f, "coach": NAMES.get(str(d.get("coach")), str(d.get("coach")))}
        parts.append(f"\n## 세션 {lab}\n")
        cur = object()
        for r in d["rows"]:
            if r["chapter"] != cur:
                cur = r["chapter"]; parts.append(f"\n### {cur or '라포'}\n")
            who = "리더" if r["role"] == "user" else "●●"
            parts.append(f"- **{who}**: {mask(r['content'] or '').replace(chr(10), ' ')}")
    open(out_md, "w", encoding="utf-8").write("\n".join(parts))
    json.dump(key, open(key_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("written", out_md, "key", key_json, {k: v["coach"] for k, v in key.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3:]))
