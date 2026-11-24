"""(2026-11-23 P16-1) 코치 턴 새 방식 — 사례 안 코치 턴을 '호출 하나'로 만든다. 환경 변수 FM_COACH_V2=1 일 때만 쓴다(기본은 종전 경로).

11/23 운영(55415bc) Lucas 일관리·자기관리 실세션: 메아리는 사라졌지만 답에 대한 반응이 없고, 사실 하나만 묻는 좁은 질문이 많고,
수준을 가르는 것(결과의 크기, 팀의 방식으로 남았는지)을 묻지 않았다. P16-0 가림 비교(12개 지점)에서 사용자는 실제 코치 턴을 한 번도 고르지 않고
새 방식(Haiku 6 · Sonnet 3)을 골랐다 — 규칙을 더 얹지 않고 질문을 만드는 방식을 바꾼다.

새 경로에서 쓰지 않는 것: 첫 꼬리 전용 호출 · 본 호출의 꼬리 질문 · 구체화 질문 · 대체 문장 · 꼬리 질문의 겉모양 검사(어절 수·리더 낱말·옮긴 부분 길이·청하는 꼴 변환).
그대로 두는 것: 슬롯 판정 · 예산 · 사례를 열고 닫는 상태 기계 · 누설 검사 · 말투 검사 · 여는 질문 사전 · 라포·영역 정의·영역 요약 · 같은 답 반복 처리.

  mid   사례 중간 턴 — 질문 하나. 반응 한 문장을 붙일지는 코드가 정한다(세 턴에 한 번 이하, 연속 없음 — reaction_allowed).
  wrap  사례 마무리 턴 — 상태 기계가 사례를 닫으려 할 때(또는 이번 질문이 그 사례의 마지막 질문일 때) 닫기 전에 한 번.
        이해한 바를 한 문장으로 확인하고, 아직 듣지 못한 것 하나를 밝힌 뒤 질문 하나. 물을 것이 없으면 확인만 한다(질문 없음 → 호출자가 바로 닫는다).

(2026-11-24 P16-1 판정) p16v2 시뮬: 되풀이형 반응이 연달아 나오고 첫 어절 '리더님' 11/20 · 끝맺음 '수 있을까요' 11/20 · 마무리 턴 4~5문장 —
  11/18 에 지적된 메아리와 같은 인상. 반응을 붙일지는 코드가 정하고(붙인 반응이 직전 답과 내용 낱말 셋 이상 겹치면 그 문장만 지운다),
  문장 머리 호칭은 코드로 떼고, 값 매기는 말이 든 문장은 지우고, 질문은 하나만 남긴다. 허락을 구하는 끝맺음·둘 중 고르기·예아니오·직전 코치 턴과 같은
  끝 두 어절은 한 번 다시 쓴다(다시 쓰기는 호출 오류·확인 탈락과 합쳐 턴당 한 번). 마무리 턴은 '아직 듣지 못한' 뜻의 말을 누설로 보지 않는다.

입력: 영역 정의 · 하위역량 · 수준 서술과 수준을 가르는 조건(게이트 규칙 6·9) · 이 사례의 대화 전체 · 이 영역에서 코치가 이미 한 말 · 코치 말투 · 아직 덜 찬 칸.
지시는 원칙만 적는다(예시 문장 없음). 출력 확인은 말투·누설·(mid 는) 질문 유무 — 걸리면 한 번 다시 부르고, 그래도 안 되면 None(호출자는 종전 경로의 턴을 쓴다).
"""
from __future__ import annotations

import logging
import os
import re

from diag_project.services.output_guard import is_question, split_sentences

logger = logging.getLogger(__name__)

MAX_TOKENS = 400
_HEAD_RE = re.compile(r"^\s*(?:\d+\s*[.)]|[-•·*])\s*")


def enabled() -> bool:
    return os.getenv("FM_COACH_V2") == "1"


# ── 마무리 턴을 언제 쓰는가(순수 함수 — 상태 기계의 값을 읽기만 한다) ─────────────────────────────
def _turn_cap(ep: dict | None) -> int:
    from diag_project.services import bei_engine as B
    return B.SWEEP_PROMOTE_MAX_TURNS if (ep or {}).get("kind") == "sweep" else B.episode_turn_max()


def last_question_next(ep: dict | None, store: dict | None, chapter: str | None, all_subs: list[str] | None) -> bool:
    """이번 코치 질문이 이 사례의 마지막 질문이 되는가 — 다음 리더 답 뒤에는 턴 상한·예산·미질문 예약으로 사례가 닫힌다.
    그렇다면 그 마지막 질문을 마무리 턴으로 쓴다(턴을 더 쓰지 않는다)."""
    from diag_project.services import bei_engine as B
    if not ep or ep.get("wrap_asked"):
        return False
    if int(ep.get("leader_turns") or 0) + 1 >= _turn_cap(ep):
        return True
    rem = B.remaining(store, chapter)
    return rem - 1 <= 0 or (bool(all_subs) and rem - 1 <= B.reserve_turns(store, chapter, list(all_subs or [])))


def can_extend(ep: dict | None, store: dict | None, chapter: str | None, all_subs: list[str] | None) -> bool:
    """상태 기계가 지금 닫으려는 사례(여섯 가지가 다 나왔거나 진전이 없다)에 마무리 턴 한 번을 더 쓸 수 있는가 —
    사례 턴 상한과 영역 예산·미질문 예약 안에서만(세션 길이를 늘리지 않는다)."""
    from diag_project.services import bei_engine as B
    if not ep or ep.get("wrap_asked") or not B.filled_slots(ep):
        return False
    if int(ep.get("leader_turns") or 0) >= _turn_cap(ep):
        return False
    rem = B.remaining(store, chapter)
    return rem > 0 and rem > B.reserve_turns(store, chapter, list(all_subs or []))


# ── 지시문 ──────────────────────────────────────────────────────────────────────────
def level_block(chapter: str, sub_name: str | None) -> str:
    """수준 기준 — 그 하위역량의 Lv.1~4 서술과 행동 예시(data/competencies.py), 수준을 가르는 조건(services/level_gate.py 규칙 1·3·6·9)."""
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK
    inds = (COMPETENCY_FRAMEWORK.get(chapter) or {}).get("indicators") or {}
    picked = [v for v in inds.values() if v.get("name") == sub_name] or list(inds.values())
    out: list[str] = []
    for ind in picked:
        out.append(f"[{ind['name']}]")
        for lv in (1, 2, 3, 4):
            ex = " / ".join(x.strip("・ ").strip() for x in str((ind.get("examples") or {}).get(lv, "")).split("\n") if x.strip())
            out.append(f"  Lv.{lv}: {ind['levels'][lv]}" + (f" (예: {ex})" if ex else ""))
    out.append("[수준을 가르는 조건]")
    out.append("  - 리더가 실제로 한 구체 행동(때·상황·한 일)이어야 근거가 된다. 태도·일반론·그런 일이 없다는 답은 근거가 아니다.")
    out.append("  - Lv.2 와 Lv.3: 기존 기준을 따라 점검·공유만 했으면 Lv.2. 리더가 기준·틀·지표·절차를 직접 제안했고 그것이 팀의 합의·운영 방식이 됐으면 Lv.3.")
    out.append("  - Lv.3 과 Lv.4: Lv.4 는 행동의 범위가 팀 밖(타 부서·다른 팀·전사·외부 기관)일 때만. 팀 안에서 만든 장치는 아무리 정착했어도 Lv.3 이 상한.")
    out.append("  - 어느 수준이든 그 수준의 핵심 행동이 발화에 실제로 있어야 한다. 하나라도 빠지면 한 단계 아래로 본다.")
    return "\n".join(out)


_COMMON_BAN = (
    "- 리더가 이미 답한 것을 다시 묻지 않는다. 리더가 하지 않은 말을 전제로 삼지 않는다.\n"
    "- 일어나지 않은 일을 가정해 묻지 않는다. 다른 사람의 속마음을 묻지 않는다.\n"
    "- 예·아니오로 답할 수 있는 질문은 쓰지 않는다.\n"
    "- 수준 이름, 하위역량 이름, 무엇을 채웠고 무엇이 남았는지 같은 안쪽 낱말은 리더에게 말하지 않는다.\n"
)


_Q_FORM = (
    "- 무엇을·어떻게·왜를 직접 묻는 말로 끝낸다. 해 줄 수 있는지 허락을 구하는 말로 끝내지 않는다. 둘 가운데 고르게 하지 않는다.\n"
    "- 직전 코치 턴과 같은 말로 끝내지 않는다.\n"
)


def build_system(mode: str, persona_name: str | None, *, react: bool = False) -> str:
    """react — 사례 중간 턴에서 이번 턴에 반응 한 문장을 붙이는가(코드가 정해 넘긴다). 마무리 턴에서는 쓰지 않는다."""
    from diag_project.services.persona_register import register_hint
    head = ("당신은 경험 많은 역량 면접관입니다. 목적은 이 사례에서 리더가 실제로 한 행동·판단·결과를 수준을 가릴 수 있을 만큼 듣는 것입니다.\n\n")
    voice = f"[말투] {register_hint(persona_name)} 리더를 부를 때는 '리더님'이라고만 한다."
    if mode == "wrap":
        return (
            head
            + "이 턴은 지금 듣고 있는 사례에서 코치가 하는 마지막 말입니다.\n\n"
            "[출력 — 이 순서로, 문장 셋 이하]\n"
            "- 간추림 한 문장(스물다섯 어절 안팎): 이 사례에서 리더가 한 일을 줄여 적고, 코치 자신이 그렇게 이해했다는 말로 맺는다. "
            "이해한 사람은 코치다 — 리더가 이해했다는 문장이 되지 않게 쓴다. 확실히 들었다고 단정하지 않는다.\n"
            "- 아직 듣지 못한 것이 있으면 그 가운데 하나만 골라 무엇인지 짧게 밝히고, 그것을 묻는 질문 한 문장을 쓴다.\n"
            "- 물을 것이 없으면 간추림 한 문장만 쓴다. 사례를 닫는다거나 다음으로 넘어간다는 말은 쓰지 않는다.\n"
            "- 그 밖의 설명·머리말·번호·따옴표는 쓰지 않는다.\n\n"
            "[묻는 것 — 하나만]\n"
            "- 이 사례에서 아직 나오지 않은 것 가운데 고른다 — 결과의 크기, 그 방식이 팀의 운영 방식이 됐는지, 팀 밖(다른 부서·전사·외부)으로 이어졌는지, 사례가 어떻게 끝났는지.\n"
            "- 그 방식이 팀의 운영 방식이 됐다는 것을 이미 들었으면 팀 밖으로 이어졌는지를 묻는다.\n"
            "- 리더가 모른다, 기억나지 않는다고 답한 것은 다시 묻지 않는다.\n\n"
            "[질문 꼴]\n"
            + _Q_FORM + "\n"
            "[지킬 것]\n"
            "- 간추림은 리더가 한 말로만 쓴다. 평가·칭찬·짐작을 보태지 않는다.\n"
            + _COMMON_BAN + "\n" + voice
        )
    shape = (
        "[이번 턴의 꼴]\n"
        "- 반응 한 문장을 먼저 쓰고, 이어서 질문 한 문장을 쓴다.\n"
        "- 그 밖의 설명·머리말·번호·따옴표는 쓰지 않는다.\n\n"
        "[반응]\n"
        "- 리더가 쓰지 않은 말로 쓴다 — 상황의 어려움을 알아주거나 답의 뜻을 한마디로 짚는다. 리더가 쓴 낱말을 옮겨 적지 않는다.\n"
        "- 칭찬하지 않는다. 리더가 한 일이나 결과에 값을 매기는 말을 쓰지 않는다.\n"
        "- 무엇이 드러났고 무엇이 아직 남았는지를 말로 풀어 설명하지 않는다.\n\n"
    ) if react else (
        "[이번 턴의 꼴]\n"
        "- 질문 한 문장만 쓴다. 반응·받는 말·간추림 같은 다른 문장은 붙이지 않는다.\n"
        "- 그 밖의 설명·머리말·번호·따옴표는 쓰지 않는다.\n\n"
    )
    return (
        head
        + shape
        + "[질문 고르기]\n"
        "- 지금까지 들은 것 가운데 가장 덜 드러난 것 하나를 묻는다 — 리더 본인의 구체 행동, 그렇게 판단한 까닭, 결과의 크기, 팀원에게 어떻게 했는지, "
        "그 방식이 이후 팀에 남았는지, 사례가 어떻게 끝났는지.\n"
        "- 그 방식이 팀의 운영 방식이 됐는지, 팀 밖(다른 부서·전사·외부)으로 이어졌는지.\n\n"
        "[질문 꼴]\n"
        "- 넓게 묻는 열린 질문을 먼저 쓴다. 사실 하나만 묻는 질문은 꼭 필요할 때만 쓴다.\n"
        "- 한 번에 하나만 묻는다.\n"
        + _Q_FORM + "\n"
        "[금지]\n"
        + _COMMON_BAN + "\n" + voice
    )


def build_user(*, chapter: str, sub_name: str | None, case: list[tuple[str, str]], coach_said: list[str], missing: list[str], note: str | None = None) -> str:
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK
    comp = COMPETENCY_FRAMEWORK.get(chapter) or {}
    convo = "\n".join(f"{'코치' if r == 'model' else '리더'}: {re.sub(chr(10) + '+', ' ', t or '').strip()}" for r, t in (case or []))
    said = "\n".join(f"- {re.sub(chr(10) + '+', ' ', t or '').strip()[:300]}" for t in (coach_said or [])[-12:]) or "- (없음)"
    return (
        f"[영역] {comp.get('name', chapter)} — {comp.get('description', '')}\n"
        f"[지금 다루는 하위역량] {sub_name or '(정해지지 않음 — 이 영역의 하위역량 전체를 참고)'}\n\n"
        f"[수준 기준 — 코치만 보는 자료]\n{level_block(chapter, sub_name)}\n\n"
        f"[이 사례에서 아직 덜 들은 것 — 코치만 보는 자료]\n{', '.join(missing) if missing else '(없음)'}\n\n"
        f"[이 영역에서 코치가 이미 한 말]\n{said}\n\n"
        f"[이 사례의 대화 — 마지막 줄이 리더가 방금 한 답]\n{convo}\n\n"
        + (f"[다시 쓰기] {note}\n\n" if note else "")
        + "이제 코치가 할 말을 씁니다."
    )


# ── 출력 정리·확인 ────────────────────────────────────────────────────────────────────
def clean(raw: str | None) -> str:
    """머리의 번호·글머리표와 통째로 감싼 따옴표를 떼고 한 줄로."""
    lines = [_HEAD_RE.sub("", ln).strip() for ln in (raw or "").split("\n")]
    t = re.sub(r"\s+", " ", " ".join(ln for ln in lines if ln)).strip()
    if len(t) >= 2 and t[0] in "\"“'‘" and t[-1] in "\"”'’":
        t = t[1:-1].strip()
    return t


def has_question(text: str | None) -> bool:
    return any(is_question(x) for x in split_sentences(text or "") if x.strip())


# ── (P16-1 판정) 반응을 붙이는 턴 · 출력 다듬기 · 질문 꼴 ──────────────────────────────────────
REACT_EVERY = 3                    # 반응을 붙일 수 있는 턴은 세 턴에 한 번 이하
REACT_SHARED_MAX = 3               # 반응 문장이 직전 답과 겹치는 내용 낱말이 이 수 이상이면 그 문장을 지운다
_EVAL_RE = re.compile(r"인상적|인상\s*깊|분명히\s*들렸|분명히\s*보입|의미\s*있는")
_PERMIT_END_RE = re.compile(r"(수\s*있(을까요|으실까요|겠습니까|으시겠습니까|나요|으신가요|습니까|으십니까)|될까요|되겠습니까|괜찮을까요|괜찮겠습니까)[?.!…\s]*$")
_ALT_RE = re.compile(r"(아니면|혹은|또는)\s")
_UNHEARD_RE = re.compile(r"아직\s*(여쭙지|여쭤보지|묻지|듣지|확인하지|다루지)\s*(않은|못한)")
_END_PUNCT_RE = re.compile(r"[?.!…\s]+$")
RETRY_NOTES = {
    "permit": "앞서 쓴 질문은 허락을 구하는 말로 끝났다. 무엇을·어떻게·왜를 직접 묻는 말로 끝낸다.",
    "alt": "앞서 쓴 질문은 둘 가운데 고르게 했다. 고르게 하지 말고 열어서 묻는다.",
    "yesno": "앞서 쓴 질문은 예·아니오로 답할 수 있었다. 무엇을·어떻게·왜로 묻는다.",
    "same_end": "앞서 쓴 문장은 직전 코치 턴과 같은 말로 끝났다. 끝맺는 말을 바꾼다.",
}


def reaction_allowed(case: list[tuple[str, str]] | None) -> bool:
    """이번 사례 중간 턴에 반응 한 문장을 붙여도 되는가 — 이 사례에서 리더가 답한 횟수가 1, 4, 7…번째일 때만.
    세 턴에 한 번 이하이고 연달아 붙지 않는다(답 횟수는 턴마다 하나씩 는다)."""
    n = sum(1 for r, _ in (case or []) if r == "user")
    return n >= 1 and n % REACT_EVERY == 1


def end_key(text: str | None) -> str:
    """끝 두 어절(끝의 문장부호는 뗀다) — 직전 코치 턴과 끝맺음이 같은지 견주는 열쇠."""
    return " ".join(_END_PUNCT_RE.sub("", (text or "").strip()).split()[-2:])


def tidy(text: str | None, *, mode: str, react: bool, last_answer: str | None) -> tuple[str, dict]:
    """모델이 쓴 코치 말을 다듬는다 — (결과, 기록).
    문장 머리 호칭을 떼고 · 값 매기는 말이 든 문장을 지우고 · 질문은 첫 질문 하나만 남기고(그 뒤는 버린다) ·
    사례 중간 턴의 평서문은 반응을 붙이는 턴에만 한 문장 남긴다(직전 답과 내용 낱말이 셋 이상 겹치면 그 문장도 지운다)."""
    from diag_project.services.turn_checks import receive_shared_words, strip_lead_address_q
    info: dict = {}
    raw = (text or "").strip()
    t = strip_lead_address_q(re.sub(r"(^|(?<=[.?!…]\s))리더님,\s*", "", raw))
    if t != raw:
        info["addr"] = 1
    sents = [x.strip() for x in split_sentences(t) if x.strip()]
    had_q = any(is_question(x) for x in sents)
    kept = [x for x in sents if not _EVAL_RE.search(x)]
    if len(kept) != len(sents):
        info["eval_cut"] = len(sents) - len(kept)
    qi = next((i for i, x in enumerate(kept) if is_question(x)), None)
    if qi is not None:
        extra_q = sum(1 for x in kept[qi + 1:] if is_question(x))
        if extra_q:
            info["q_cut"] = extra_q
        stmts, q = kept[:qi], [kept[qi]]
    else:
        stmts, q = kept, []
    if mode == "mid":
        cut: list[str] = []
        if stmts and not react:
            cut += ["not_allowed"] * len(stmts)
            stmts = []
        elif stmts:
            cut += ["extra"] * (len(stmts) - 1)
            stmts = stmts[:1]
            if len(receive_shared_words(stmts[0], last_answer or "")) >= REACT_SHARED_MAX:
                cut.append("overlap")
                stmts = []
        if cut:
            info["react_cut"] = cut
        info["react"] = int(bool(stmts))
    if had_q and not q:
        info["q_lost"] = 1
    return " ".join(stmts + q).strip(), info


def question_issue(text: str | None, prev_coach: str | None) -> str | None:
    """질문 꼴에서 한 번 다시 쓰게 할 것 — permit(허락을 구하는 끝맺음) | alt(둘 중 고르기) | yesno(예·아니오) | same_end(직전 코치 턴과 끝 두 어절이 같다). 없으면 None."""
    from diag_project.services.turn_checks import _FP_ASK_FOR_RE, _FP_WH_RE
    q = next((x.strip() for x in reversed(split_sentences(text or "")) if x.strip() and is_question(x)), "")
    if not q:
        return None
    if _PERMIT_END_RE.search(q):
        return "permit"
    if _ALT_RE.search(q):
        return "alt"
    if not _FP_WH_RE.search(q) and not _FP_ASK_FOR_RE.search(q):
        return "yesno"
    if prev_coach and end_key(text) and end_key(text) == end_key(prev_coach):
        return "same_end"
    return None


def check(text: str | None, *, mode: str, persona_name: str | None, leader_texts: list[str] | None) -> tuple[bool, str]:
    """(통과, 사유: ok | empty | closed_tag | no_question | register | leak). 어절 수·낱말 겹침은 보지 않는다."""
    from diag_project.services.leak_lexicon import find_leaks, find_state_report
    from diag_project.services.output_guard import find_state_leak
    from diag_project.services.persona_register import register_violations
    t = (text or "").strip()
    if not t:
        return False, "empty"
    if "[닫음]" in t or t.startswith("["):
        return False, "closed_tag"
    if mode == "mid" and not has_question(t):
        return False, "no_question"
    if register_violations(persona_name, t, scope="all"):
        return False, "register"
    # 누설 검사 — 안쪽 낱말(가드 사전)·칸 이름·진행 상태를 알리는 말. 마무리 턴은 이해한 것과 덜 들은 것을 말하는 턴이라
    #   '아직 듣지 못한 …' 뜻의 말만 누설로 보지 않는다(P16-1 판정 — p16v2: 이 말에 걸려 마무리 턴 두 건이 통째로 떨어졌다). 닫는다고 알리는 말은 그대로 걸린다.
    hits = [h for h in find_leaks(t, list(leader_texts or []), strict=True) if not (mode == "wrap" and _UNHEARD_RE.search(h))]
    if hits or find_state_leak(t) or (mode == "mid" and find_state_report(t)):
        return False, "leak"
    return True, "ok"


async def render(llm, *, mode: str, chapter: str, sub_name: str | None, case: list[tuple[str, str]], coach_said: list[str], missing: list[str],
                 persona_name: str | None, trace: list | None = None, meta: dict | None = None) -> tuple[str | None, str]:
    """(코치 턴 | None, 기록). 기록 'llm' | 'llm_retry' | 'llm_first'(다시 쓴 것이 떨어져 처음 것을 씀) | 'stub' | 'miss:<사유>'.
    호출 오류·확인 탈락·질문 꼴(question_issue) 가운데 무엇이든 걸리면 한 번만 다시 부른다(턴당 합쳐 한 번).
    다시 쓴 것에 질문 꼴이 남아 있으면 그대로 쓴다(meta['left']). meta 에는 다듬은 기록(tidy)과 다시 쓴 까닭(rewrite)을 남긴다."""
    meta = meta if meta is not None else {}
    if os.getenv("FM_LLM_STUB"):
        return None, "stub"
    if llm is None or not case:
        return None, "miss:no_llm" if llm is None else "miss:no_material"
    react = mode == "mid" and reaction_allowed(case)
    meta["react_slot"] = int(react)
    system = build_system(mode, persona_name, react=react)
    leader_texts = [t for r, t in case if r == "user"]
    last_answer = leader_texts[-1] if leader_texts else ""
    prev_coach = (coach_said or [""])[-1] if coach_said else ""
    why, note, first = "empty", None, None
    for attempt in (0, 1):
        user = build_user(chapter=chapter, sub_name=sub_name, case=case, coach_said=coach_said, missing=missing, note=note)
        try:
            out = await llm._generate_with_retry(prompt=user, system_instruction=system, max_tokens=MAX_TOKENS, thinking_budget=0,
                                                 call_type=f"coach_v2_{mode}", temperature=0.4)
        except Exception as e:  # noqa: BLE001
            logger.warning("coach v2 render failed: %s", e)
            why = "error"
            continue
        text, info = tidy(clean(out), mode=mode, react=react, last_answer=last_answer)
        ok, why = check(text, mode=mode, persona_name=persona_name, leader_texts=leader_texts)
        if ok and info.get("q_lost"):
            ok, why = False, "no_question"
        if not ok:
            if trace is not None:
                trace.append([f"coach_v2:{mode}", why, text[:200]])
            continue
        issue = question_issue(text, prev_coach)
        if issue and attempt == 0:
            first = (text, info)
            note = RETRY_NOTES[issue]
            meta["rewrite"] = issue
            if trace is not None:
                trace.append([f"coach_v2:{mode}", f"rewrite:{issue}", text[:200]])
            continue
        meta.update(info)
        if issue:
            meta["left"] = issue
        return text, ("llm_retry" if attempt else "llm")
    if first:
        # 다시 쓴 것이 확인에서 떨어졌다 — 처음 쓴 것(질문 꼴만 걸린 것)을 쓴다. 종전 경로로 넘기지 않는다.
        meta.update(first[1])
        meta["left"] = meta.get("rewrite")
        return first[0], "llm_first"
    return None, f"miss:{why}"
