"""10/26~28 운영 세션 재현 체크 (2026-10-29) — 재생 결과 JSON 에서 세션별 재현 항목을 자동 확인한다.

용법: python tools/p0_repro_check.py .fm_work/replay_result_s28{1,2,3,4,5}_{2,3,4,5,6}.json
항목(사용자 지정):
  Jessica: 사람관리 정의 질문에 코치 질문 복사 → QUESTION_RETURNED / '짧게 답하셨' 0건 / 일관리 ALIGN 목록 전부(competencies 기준 개수)
  Olivia : 'sp' → CONFIRM_REASK 뒤 정의 질문(DIAGNOSIS_CONFIRM·COMPETENCY_ASK) 이 나감 / 코치 발화에 '로서' 자기 지칭 0건
  Daniel : 같은 답 2회 → INPUT_REPEATED / '네?' → ANCHOR_REASK / 조직·성과·사람 ALIGN 목록 전부
  Michael: 성과관리 ALIGN 목록 '· ' 줄 / 사람관리 '네' 뒤 오류 턴(LLM_ERROR·HTTP 오류) 0건
  Lucas  : 일관리 ALIGN 에 '조직을 효과적으로' 0건 / 자기관리 정의 질문→ALIGN 사이 탐침 0턴 (13:49 인사는 단위 테스트로 확인)
"""
import json
import re
import sys
from collections import defaultdict

sys.path.insert(0, ".")
from diag_project.data.competencies import COMPETENCY_FRAMEWORK  # noqa: E402

NAMES = {"2": "Jessica", "3": "Olivia", "4": "Daniel", "5": "Michael", "6": "Lucas"}
ANOMALY = {"INPUT_REPEATED", "INPUT_DUPLICATE", "QUESTION_RETURNED", "QUESTION_REASK", "CONFIRM_REASK", "DEFINITION_REASK", "ANCHOR_REASK"}


def subs(ch):
    return [i["name"] for i in COMPETENCY_FRAMEWORK[ch]["indicators"].values()]


def align_full(text, ch):
    listed = {l.strip()[1:].strip() for l in text.split("\n") if l.strip().startswith("·")}
    return all(n in listed for n in subs(ch)), len(subs(ch))


def check(path):
    d = json.load(open(path, encoding="utf-8"))
    coach = d["coach"]; name = NAMES.get(coach, coach); rows = d["rows"]
    out = {"file": path.split("/")[-1], "coach": name, "status": d.get("status"), "topic": d.get("topic")}
    models = [(i, r) for i, r in enumerate(rows) if r["role"] == "model"]
    users = [(i, r) for i, r in enumerate(rows) if r["role"] == "user"]
    coach_text = "\n".join(r["content"] for _, r in models)

    def next_model(i):
        return next((r for j, r in models if j > i), None)

    def prev_model(i):
        return next((r for j, r in reversed(models) if j < i), None)

    # 공통: 앵커 재질문·입력 이상 턴 목록
    out["anomaly_turns"] = [(r["chapter"], r["instr"]) for _, r in models if r["instr"] in ANOMALY]
    out["짧게 답하셨"] = len(re.findall(r"짧게\s*답하", coach_text))
    out["로서 자기지칭"] = len(re.findall(r"(코치로서|Olivia\s*로서|올리비아로서|Jessica\s*로서|Daniel\s*로서|Michael\s*로서|Lucas\s*로서|저로서는)", coach_text))
    out["조직을 효과적으로(일관리 ALIGN)"] = sum(1 for _, r in models if r["instr"] == "COMPETENCY_ALIGN" and r["chapter"] == "work_management" and "조직을 효과적으로" in r["content"])
    aligns = {}
    for _, r in models:
        if r["instr"] == "COMPETENCY_ALIGN":
            ok, n = align_full(r["content"], r["chapter"])
            aligns[r["chapter"]] = f"{'전부' if ok else '누락'}({n}개)" + ("" if "\n· " in r["content"] else " · 줄 아님")
    out["ALIGN 목록"] = aligns
    # 코치 질문 붙여넣기 → QUESTION_RETURNED
    pasted = []
    for i, r in users:
        pm = prev_model(i)
        if pm and len(r["content"]) > 20 and re.sub(r"\s", "", r["content"])[:30] in re.sub(r"\s", "", pm["content"]):
            nm = next_model(i)
            pasted.append((r["chapter"], (nm or {}).get("instr")))
    out["코치 질문 붙여넣기 → 응답"] = pasted
    # 같은 답 2회 → INPUT_REPEATED
    rep = []
    for (i, r), (j, p) in zip(users[1:], users[:-1]):
        if len(r["content"]) >= 10 and re.sub(r"\s", "", r["content"]) == re.sub(r"\s", "", p["content"]):
            nm = next_model(i)
            rep.append((r["chapter"], (nm or {}).get("instr"), r["content"][:30]))
    out["같은 답 2회 → 응답"] = rep
    # 'sp' / '네?' / '네' 뒤 응답
    specials = []
    for i, r in users:
        if r["content"].strip() in ("sp", "네?", "??", "네", "넵"):
            nm = next_model(i)
            specials.append((r["content"].strip(), r["chapter"], (nm or {}).get("instr")))
    out["짧은 입력 → 응답"] = specials[:12]
    # 'sp' 뒤 정의 질문이 나갔는가
    sp_idx = next((i for i, r in users if r["content"].strip() == "sp"), None)
    if sp_idx is not None:
        after = [r["instr"] for j, r in models if j > sp_idx][:4]
        out["sp 뒤 코치 흐름"] = after
    # 오류 턴
    out["오류 턴(LLM_ERROR)"] = sum(1 for _, r in models if (r.get("guard") or {}).get("instr") == "LLM_ERROR" or "다시 시도" in r["content"][:40])
    # 자기관리 정의→ALIGN 사이 턴
    sm = [r for _, r in models if r["chapter"] == "self_management"]
    try:
        a = next(i for i, r in enumerate(sm) if r["instr"] in ("COMPETENCY_ASK", "DIAGNOSIS_CONFIRM"))
        b = next(i for i, r in enumerate(sm) if r["instr"] == "COMPETENCY_ALIGN")
        out["자기관리 정의→ALIGN 사이 턴"] = [r["instr"] for r in sm[a + 1:b]]
    except StopIteration:
        out["자기관리 정의→ALIGN 사이 턴"] = "자기관리 미도달" if not sm else "정의/ALIGN 없음"
    return out


if __name__ == "__main__":
    by_coach = defaultdict(list)
    for p in sys.argv[1:]:
        o = check(p); by_coach[o["coach"]].append(o)
    for c in ("Jessica", "Olivia", "Daniel", "Michael", "Lucas"):
        print(f"\n### {c}")
        for o in by_coach.get(c, []):
            print(f"- {o['file']} [{o['status']}/{o['topic']}]")
            for k, v in o.items():
                if k in ("file", "coach", "status", "topic"):
                    continue
                print(f"    {k}: {v}")
