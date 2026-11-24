"""(2026-11-23 P16-1) 코치 턴 새 방식 — 사례 안 코치 턴을 '호출 하나'로 만든다. 환경 변수 FM_COACH_V2=1 일 때만 쓴다(기본은 종전 경로).

11/23 운영(55415bc) Lucas 일관리·자기관리 실세션: 메아리는 사라졌지만 답에 대한 반응이 없고, 사실 하나만 묻는 좁은 질문이 많고,
수준을 가르는 것(결과의 크기, 팀의 방식으로 남았는지)을 묻지 않았다. P16-0 가림 비교(12개 지점)에서 사용자는 실제 코치 턴을 한 번도 고르지 않고
새 방식(Haiku 6 · Sonnet 3)을 골랐다 — 규칙을 더 얹지 않고 질문을 만드는 방식을 바꾼다.

새 경로에서 쓰지 않는 것: 첫 꼬리 전용 호출 · 본 호출의 꼬리 질문 · 구체화 질문 · 대체 문장 · 꼬리 질문의 겉모양 검사(어절 수·리더 낱말·옮긴 부분 길이·청하는 꼴 변환).
그대로 두는 것: 슬롯 판정 · 예산 · 사례를 열고 닫는 상태 기계 · 누설 검사 · 말투 검사 · 여는 질문 사전 · 라포·영역 정의·영역 요약 · 같은 답 반복 처리.

  mid   사례 중간 턴 — 질문 하나. 반응 한 문장을 붙일지는 코드가 정한다(두 턴에 한 번, 연속 없음, 사례의 첫 꼬리 질문 턴은 붙이는 쪽 — reaction_allowed).
  wrap  사례 마무리 턴 — 상태 기계가 사례를 닫으려 할 때(또는 이번 질문이 그 사례의 마지막 질문일 때) 닫기 전에 한 번.
        세 토막: 이해한 바를 한 문장으로 확인 → 마지막 보충 확인임을 알리는 짧은 말 → 확인 안 된 것 하나를 짧게 묻는 질문. 물을 것이 없으면 첫 토막만(질문 없음 → 호출자가 바로 닫는다).

(2026-11-24 P16-1 판정) p16v2 시뮬: 되풀이형 반응이 연달아 나오고 첫 어절 '리더님' 11/20 · 끝맺음 '수 있을까요' 11/20 · 마무리 턴 4~5문장 —
  11/18 에 지적된 메아리와 같은 인상. 반응을 붙일지는 코드가 정하고(붙인 반응이 직전 답과 내용 낱말 셋 이상 겹치면 그 문장만 지운다),
  문장 머리 호칭은 코드로 떼고, 값 매기는 말이 든 문장은 지우고, 질문은 하나만 남긴다. 허락을 구하는 끝맺음·둘 중 고르기·예아니오·직전 코치 턴과 같은
  끝 두 어절은 한 번 다시 쓴다(다시 쓰기는 호출 오류·확인 탈락과 합쳐 턴당 한 번). 마무리 턴은 '아직 듣지 못한' 뜻의 말을 누설로 보지 않는다.

(2026-11-24 P16-1b 판정) 사용자가 p16v2 와 p16v2b 의 같은 사례를 나란히 읽고 정했다 — 사례 중간은 두 버전의 사이, 마무리 턴은 p16v2b 길이로 하되
  끝 질문이 계속 이어지는 열린 질문처럼 들리지 않게 '확인되지 않은 부분의 보충 질문'으로. 반응은 그 사례에서 나간 중간 턴 순번으로 두 턴에 한 번(첫 꼬리 질문 턴부터),
  열두 어절 이하 한 문장이고 리더의 낱말을 일부 써도 된다(직전 답과 내용 낱말 다섯 이상 겹치거나 열두 어절을 넘을 때만 지운다). 끝 두 어절은 앞의 두 코치 턴과 견준다.
  마무리 턴은 예아니오·고르기 다시 쓰기 대상이 아니다(확인 질문). 마무리 턴의 누설 검사는 '하나만 더 확인' 뜻의 말과 간추린 문장 속 보통 낱말 '없음'을 봐준다(사전은 그대로).

(2026-11-24 P16-1c 판정) 사용자가 p16v2c 전문 전체를 읽고 네 가지를 짚었다 — ① 한 턴 한 물음: 문장이 하나여도 물음이 둘이면 다시 쓴다(two_asks)
  ② 이 영역에서 이미 나간 반응과 내용 낱말 둘 이상 겹치는 반응은 지운다 ③ 마무리 턴을 코드로도 확인한다 — 세 토막 밖의 문장은 지우고, 확인 질문이 열다섯 어절을 넘거나
  물음이 둘이거나 청하는 말·궁금하다는 말로 끝나면 한 번 다시 쓴다 ④ 팀의 방식이 됐는지·팀 밖으로 이어졌는지는 그 사례의 세 번째 중간 턴부터만 고를 수 있다.

(2026-11-24 P16-1d 판정) 6코치 회귀 p16v2d: 흐름은 양호, 마무리 턴의 반복만 고친다 — ① 마무리 턴의 둘째 토막(하나만 더 확인한다는 말)은 모델이 쓰지 않고
  코드가 고정 문구(WRAP_NOTICES)에서 고른다(영역 안에서 안 쓴 것부터). 모델은 첫째 토막(이해 확인)과 확인 질문만 쓴다. 질문이 없으면 둘째 토막도 붙이지 않는다
  ② 팀 밖으로 이어졌는지를 묻는 마무리 질문은 리더가 남에게 옮길 수 있는 것(기준·절차·양식·도구)을 만들었다고 말한 때에만, 영역당 두 번까지(BEYOND_MAX — 코드가 센다)
  ③ 묻는 꼴이 아닌 끝('궁금해요', '여쭤볼게요')에 붙은 물음표는 마침표로, 마무리 턴의 확인 질문이 그런 말로 끝나면 다시 쓴다
  ④ 사례 중간 턴의 반응 문장이 누설 검사에 걸리면 턴 전체가 아니라 그 문장만 지운다 ⑤ 값 매기는 말에 '눈에 띄' 추가.

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


_BAN_BASE = (
    "- 리더가 이미 답한 것을 다시 묻지 않는다. 리더가 하지 않은 말을 전제로 삼지 않는다.\n"
    "- 일어나지 않은 일을 가정해 묻지 않는다. 다른 사람의 속마음을 묻지 않는다.\n"
)
_BAN_INNER = "- 수준 이름, 하위역량 이름, 무엇을 채웠고 무엇이 남았는지 같은 안쪽 낱말은 리더에게 말하지 않는다.\n"
_COMMON_BAN = _BAN_BASE + "- 예·아니오로 답할 수 있는 질문은 쓰지 않는다.\n" + _BAN_INNER


def build_system(mode: str, persona_name: str | None, *, react: bool = False, team_q: bool = True, beyond_ok: bool = True) -> str:
    """react — 사례 중간 턴에서 이번 턴에 반응 한 문장을 붙이는가(코드가 정해 넘긴다). 마무리 턴에서는 쓰지 않는다.
    team_q — 사례 중간 턴에서 팀의 방식이 됐는지·팀 밖으로 이어졌는지를 고를 수 있는 턴인가(그 사례의 세 번째 중간 턴부터 — team_question_allowed).
    beyond_ok — 마무리 턴에서 팀 밖으로 이어졌는지를 고를 수 있는가(이 영역에서 그 물음이 BEYOND_MAX 번에 못 미쳤을 때)."""
    from diag_project.services.persona_register import register_hint
    head = ("당신은 경험 많은 역량 면접관입니다. 목적은 이 사례에서 리더가 실제로 한 행동·판단·결과를 수준을 가릴 수 있을 만큼 듣는 것입니다.\n\n")
    voice = f"[말투] {register_hint(persona_name)} 리더를 부를 때는 '리더님'이라고만 한다."
    if mode == "wrap":
        beyond = ("- 팀 밖(다른 부서·전사·외부)으로 이어졌는지 — 리더가 이 일에서 기준·절차·양식·도구처럼 남에게 옮길 수 있는 것을 만들었다고 말한 때에만 고른다.\n"
                  if beyond_ok else "- 팀 밖으로 이어졌는지는 이 턴에서 묻지 않는다.\n")
        return (
            head.replace("이 사례에서", "이 일에서")      # 마무리 턴 지시문에는 '사례'라는 낱말을 쓰지 않는다(모델이 '이 사례에서 …'로 옮겨 써 린트에 걸렸다 — p16v2d)
            + "이 턴은 지금 듣고 있는 일에 대해 코치가 하는 마지막 말입니다. 두 토막을 이 순서로 씁니다.\n\n"
            "[첫째 토막]\n"
            "- 리더가 이 일에서 한 것을 한 문장(스물다섯 어절 안팎)으로 줄여 적고, 코치가 그렇게 이해했다는 말로 맺는다. 확실히 들었다고 단정하지 않는다.\n"
            "- 리더가 한 말로만 쓴다. 평가·칭찬·짐작을 보태지 않는다.\n\n"
            "[둘째 토막]\n"
            "- 아직 확인되지 않은 것 하나를 짧게 묻는 질문 한 문장(열다섯 어절 이하). 이야기를 넓게 청하는 질문이 아니라 빠진 것을 확인하는 질문이다. "
            "예·아니오로 답할 수 있는 꼴이어도 된다.\n"
            "- 물음은 하나다. 한 문장에 두 가지를 이어 묻지 않는다.\n"
            "- 묻는 말로 끝낸다. 말해 달라고 청하는 말이나 궁금하다는 말, 묻겠다고 알리는 말, 해 줄 수 있는지 허락을 구하는 말로 끝내지 않는다. "
            "앞의 두 코치 턴과 같은 말로 끝내지 않는다.\n\n"
            "[무엇을 묻는가 — 이 순서로 처음 걸리는 것 하나]\n"
            "- 일의 결과나 끝이 아직 나오지 않았으면 그것.\n"
            "- 그 방식이 팀의 운영 방식이 됐는지.\n"
            + beyond
            + "- 리더가 이미 답한 것, 모른다거나 기억나지 않는다고 답한 것은 건너뛴다. 이미 들은 것을 다시 확인하지 않는다.\n"
            "- 물을 것이 없으면 첫째 토막만 쓰고 끝낸다. 닫는다거나 다음으로 넘어간다는 말은 쓰지 않는다.\n\n"
            "[그 밖]\n"
            "- 두 토막 밖의 문장은 쓰지 않는다. 하나만 더 확인하겠다고 알리는 말은 두 토막 사이에 따로 들어가므로 쓰지 않는다. "
            "무엇을 듣지 못했는지 늘어놓지 않는다.\n"
            "- 토막의 이름·번호·머리말·따옴표는 쓰지 않는다.\n"
            + _BAN_BASE + _BAN_INNER + "\n" + voice
        )
    shape = (
        "[이번 턴의 꼴]\n"
        "- 반응 한 문장을 먼저 쓰고, 이어서 질문 한 문장을 쓴다.\n"
        "- 질문은 리더의 답을 앞 절로 되풀이하지 않고 바로 묻는다.\n"
        "- 그 밖의 설명·머리말·번호·따옴표는 쓰지 않는다.\n\n"
        "[반응]\n"
        "- 열두 어절 이하 한 문장. 상황의 어려움을 알아주거나 답의 뜻을 한마디로 짚는다.\n"
        "- 리더가 쓴 낱말을 일부 써도 된다. 답을 길게 옮겨 적지 않는다.\n"
        "- 칭찬하지 않는다. 리더가 한 일이나 결과에 값을 매기는 말을 쓰지 않는다.\n"
        "- 무엇이 드러났고 무엇이 아직 남았는지를 말로 풀어 설명하지 않는다.\n\n"
    ) if react else (
        "[이번 턴의 꼴]\n"
        "- 질문 한 문장만 쓴다. 반응·받는 말·간추림 같은 다른 문장은 붙이지 않는다.\n"
        "- 그 밖의 설명·머리말·번호·따옴표는 쓰지 않는다.\n\n"
    )
    pick = (
        "[질문 고르기]\n"
        "- 지금까지 들은 것 가운데 가장 덜 드러난 것 하나를 묻는다 — 리더 본인의 구체 행동, 그렇게 판단한 까닭, 결과의 크기, 팀원에게 어떻게 했는지, "
        "그 방식이 이후 팀에 남았는지, 사례가 어떻게 끝났는지.\n"
        "- 그 방식이 팀의 운영 방식이 됐는지, 팀 밖(다른 부서·전사·외부)으로 이어졌는지.\n\n"
    ) if team_q else (
        "[질문 고르기]\n"
        "- 지금까지 들은 것 가운데 가장 덜 드러난 것 하나를 묻는다 — 리더 본인의 구체 행동, 그렇게 판단한 까닭, 결과의 크기, 팀원에게 어떻게 했는지, "
        "사례가 어떻게 끝났는지.\n"
        "- 이번 턴은 리더 본인의 행동·판단·결과 쪽에서 고른다. 그 방식이 팀에 자리 잡았는지, 팀 밖으로 이어졌는지는 이 턴에서 묻지 않는다.\n\n"
    )
    return (
        head
        + shape
        + pick
        + "[질문 꼴]\n"
        "- 넓게 묻는 열린 질문을 먼저 쓴다. 사실 하나만 묻는 질문은 꼭 필요할 때만 쓴다.\n"
        "- 물음은 하나다. 한 문장에 두 가지를 이어 묻지 않는다.\n"
        "- 무엇을·어떻게·왜를 직접 묻는 말로 끝낸다. 해 줄 수 있는지 허락을 구하는 말로 끝내지 않는다. 둘 가운데 고르게 하지 않는다.\n"
        "- 앞의 두 코치 턴과 같은 말로 끝내지 않는다.\n\n"
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
REACT_EVERY = 2                    # 반응을 붙일 수 있는 턴은 두 턴에 한 번(P16-1b — 종전 세 턴에 한 번 이하)
REACT_SHARED_MAX = 5               # 반응 문장이 직전 답과 겹치는 내용 낱말이 이 수 이상이면 그 문장을 지운다(P16-1b — 종전 3)
REACT_MAX_EOJEOL = 12              # 반응 문장은 열두 어절 이하 — 넘으면 그 문장을 지운다
PREV_END_TURNS = 2                 # 끝 두 어절을 견주는 앞 코치 턴 수
REACT_REPEAT_MAX = 2               # (P16-1c) 이 영역에서 이미 나간 반응 문장과 겹치는 내용 낱말이 이 수 이상이면 그 반응을 지운다
TEAM_Q_FROM = 2                    # (P16-1c) 팀의 방식이 됐는지·팀 밖으로 이어졌는지는 이미 나간 중간 턴이 이 수 이상일 때부터 고를 수 있다(세 번째 중간 턴부터)
WRAP_Q_MAX_EOJEOL = 15             # (P16-1c) 마무리 턴의 확인 질문은 열다섯 어절 이하 — 넘으면 한 번 다시 쓴다
# (P16-1c) 마무리 턴의 둘째 토막 — 마지막으로 하나만 더 확인한다는 뜻의 말
_NOTICE_RE = re.compile(r"(하나|한\s*가지|마지막|끝으로).{0,24}(확인|여쭙|여쭤|묻|물어|질문)|(확인|여쭙|여쭤|질문).{0,12}(하나|한\s*가지)")
# (P16-1c) 한 문장 안에서 물음을 잇는 말 — '…는지, 그리고 …' · '…셨고 …'
_ASK_JOIN_RE = re.compile(r"(는지|은지|인지|을지)(?:를|도)?[,，]?\s*(그리고|또한|또|아울러)\s")
_ASK_JI_SPLIT_RE = re.compile(r"(?<=[가-힣])(?:는지|은지|인지)(?:를|도)?[,，]?\s+")
_EVAL_RE = re.compile(r"인상적|인상\s*깊|분명히\s*들렸|분명히\s*보입|의미\s*있는|눈에\s*[띄띕띈띌]")
_PERMIT_END_RE = re.compile(r"(수\s*있(을까요|으실까요|겠습니까|으시겠습니까|나요|으신가요|습니까|으십니까)|될까요|되겠습니까|괜찮을까요|괜찮겠습니까)[?.!…\s]*$")
_ALT_RE = re.compile(r"(아니면|혹은|또는)\s")
_UNHEARD_RE = re.compile(r"아직\s*(여쭙지|여쭤보지|묻지|듣지|확인하지|다루지)\s*(않은|못한)")
# (P16-1b) 마무리 턴에서만 누설로 보지 않는 것 — 덜 들은 것을 밝히는 말 · 마지막으로 하나만 더 확인한다는 말 · 간추린 문장 속 보통 낱말 '없음'('지연 없음').
#   누설 사전과 진행 상태 패턴은 그대로 둔다(다른 턴의 검사는 달라지지 않는다). 닫는다고 알리는 말('여기서 마무리', '여기까지 하-')은 그대로 걸린다.
_WRAP_PASS_RE = re.compile(_UNHEARD_RE.pattern + r"|(첫|다음|마지막)\s*질문|(이\s*사례에서|이제)\s*남은\s*(것|부분)은|(남은|남아\s*있는)\s*(부분|항목|질문)(은|이)|^없음$")
# 문장 머리에 나온 안쪽 표지('간추림:', '확인 질문:') · 토막 번호
_LABEL_RE = re.compile(r"(^|(?<=[.?!…]\s))(?:[①②③④]\s*|[가-힣]{2,6}(?:\s[가-힣]{2,6})?\s*[:：]\s*)")
_END_PUNCT_RE = re.compile(r"[?.!…\s]+$")
# (P16-1d) 마무리 턴의 둘째 토막 — 하나만 더 확인한다는 말. 모델이 쓰지 않고 여기서 고른다(pick_notice). 누설 검사·린트·말투 검사에 걸리지 않는 문구다.
WRAP_NOTICES = {
    "formal": ("한 가지만 더 확인하겠습니다.", "하나만 더 여쭙겠습니다.", "마지막으로 하나만 확인하겠습니다.", "끝으로 한 가지만 여쭙겠습니다.",
               "확인할 것이 하나 남았습니다.", "덧붙여 하나만 여쭙겠습니다."),
    "polite": ("한 가지만 더 확인할게요.", "하나만 더 여쭤볼게요.", "마지막으로 하나만 확인할게요.", "끝으로 한 가지만 여쭤볼게요.",
               "확인할 게 하나 남았어요.", "덧붙여 하나만 여쭤볼게요."),
}
BEYOND_MAX = 2                     # (P16-1d) 팀 밖으로 이어졌는지를 묻는 마무리 질문은 영역당 이 수까지
_BEYOND_RE = re.compile(r"팀\s*(밖|바깥)|다른\s*부서|다른\s*팀|전사|외부")
# (P16-1d) 묻겠다고 알리는 말에 붙은 물음표 — 마침표로 고친다('…궁금해요?'는 turn_checks.finish_sentence_marks 가 고친다)
_ANNOUNCE_Q_RE = re.compile(r"(여쭤볼게요|여쭤보겠습니다|여쭙겠습니다|물어볼게요|묻겠습니다)\?")
RETRY_NOTES = {
    "permit": "앞서 쓴 질문은 허락을 구하는 말로 끝났다. 무엇을·어떻게·왜를 직접 묻는 말로 끝낸다.",
    "alt": "앞서 쓴 질문은 둘 가운데 고르게 했다. 고르게 하지 말고 열어서 묻는다.",
    "yesno": "앞서 쓴 질문은 예·아니오로 답할 수 있었다. 무엇을·어떻게·왜로 묻는다.",
    "same_end": "앞서 쓴 문장은 앞의 코치 턴과 같은 말로 끝났다. 끝맺는 말을 바꾼다.",
    "two": "앞서 쓴 질문은 한 문장에 두 가지를 물었다. 하나만 묻는다.",
    "long": "앞서 쓴 확인 질문은 길었다. 열다섯 어절 이하로 하나만 묻는다.",
    "request": "앞서 쓴 확인 질문은 청하는 말이나 궁금하다는 말, 묻겠다고 알리는 말로 끝났다. 묻는 말로 끝낸다.",
    "beyond": "앞서 쓴 확인 질문은 팀 밖으로 이어졌는지를 물었다. 그 물음은 이 턴에서 쓰지 않는다. 결과나 팀의 방식 쪽에서 아직 듣지 못한 것을 묻고, 없으면 첫째 토막만 쓴다.",
}


def pick_notice(persona_name: str | None, coach_said: list[str] | None) -> str:
    """(P16-1d) 마무리 턴의 둘째 토막으로 넣을 고정 문구 — 이 영역에서 아직 쓰지 않은 것부터, 다 썼으면 가장 오래전에 쓴 것."""
    from diag_project.services.intro_messages import line_register
    pool = WRAP_NOTICES["formal" if line_register(persona_name) == "formal" else "polite"]
    said = " ".join(coach_said or [])
    unused = [x for x in pool if x not in said]
    return unused[0] if unused else min(pool, key=lambda x: said.rfind(x))


def asks_beyond(text: str | None) -> bool:
    """(P16-1d) 이 코치 말의 질문이 팀 밖(다른 부서·다른 팀·전사·외부)으로 이어졌는지를 묻는가."""
    return any(_BEYOND_RE.search(x) for x in split_sentences(text or "") if x.strip() and is_question(x))


def reaction_allowed(mid_n: int | None) -> bool:
    """이번 사례 중간 턴에 반응 한 문장을 붙여도 되는가 — mid_n 은 이 사례에서 이미 나간 중간 턴 수(다시 묻기 턴은 세지 않는다).
    사례의 첫 꼬리 질문 턴(0)부터 두 턴에 한 번 — 연달아 붙지 않는다. 영역 전체의 중간 턴 순번으로 세되 사례가 바뀌면 붙이는 쪽에서 다시 시작하는 것과 같다
    (사례 사이에는 마무리 턴과 여는 질문이 끼므로 반응이 붙은 턴이 맞닿지 않는다)."""
    return int(mid_n or 0) % REACT_EVERY == 0


def team_question_allowed(mid_n: int | None) -> bool:
    """(P16-1c) 이번 사례 중간 턴에서 팀의 방식이 됐는지·팀 밖으로 이어졌는지를 고를 수 있는가 — 그 사례의 세 번째 중간 턴부터.
    그 전에는 리더 본인의 행동·판단·결과 쪽에서 고른다."""
    return int(mid_n or 0) >= TEAM_Q_FROM


def two_asks(question: str | None) -> bool:
    """(P16-1c) 질문 한 문장 안에 물음이 둘인가 — '…어떤 순서로 나누셨고, …어떻게 배분하셨습니까' · '…됐는지, 그리고 …이어졌는지 …'.
    쉼표로 이어진 질문 덩어리(turn_checks.inline_question_clauses) · '-는지' 뒤에 그리고/또로 이은 물음 · 이음 어미로 갈린 두 쪽에 저마다 의문사가 있는 꼴."""
    from diag_project.services.turn_checks import _FP_WH_RE, inline_question_clauses
    q = (question or "").strip()
    if not q:
        return False
    if len(inline_question_clauses(q)) >= 2 or _ASK_JOIN_RE.search(q):
        return True
    if sum(1 for part in _ASK_JI_SPLIT_RE.split(q) if _FP_WH_RE.search(part)) >= 2:
        return True
    # 이음 어미('-셨고', '-였고', '-하고', '-(으)며')로 끝난 앞쪽에 의문사가 있으면 그 앞쪽도 물음이다 — 뒤쪽 물음과 합쳐 둘
    toks = q.split()
    for i, tok in enumerate(toks[:-1]):
        w = tok.rstrip(",，")
        prev = ord(w[-2]) - 0xAC00 if len(w) >= 2 else -1
        joined = (w.endswith("고") and ((0 <= prev < 11172 and prev % 28 == 20) or w.endswith("하고"))) or w.endswith(("으며", "하며", "이며"))
        if joined and _FP_WH_RE.search(" ".join(toks[:i + 1])):
            return True
    return False


def end_key(text: str | None) -> str:
    """끝 두 어절(끝의 문장부호는 뗀다) — 직전 코치 턴과 끝맺음이 같은지 견주는 열쇠."""
    return " ".join(_END_PUNCT_RE.sub("", (text or "").strip()).split()[-2:])


def tidy(text: str | None, *, mode: str, react: bool, last_answer: str | None, prior_reacts: list[str] | None = None,
         notice: str | None = None) -> tuple[str, dict]:
    """모델이 쓴 코치 말을 다듬는다 — (결과, 기록).
    문장 머리의 호칭과 안쪽 표지를 떼고 · 값 매기는 말이 든 문장을 지우고 · 질문은 첫 질문 하나만 남기고(그 뒤는 버린다) ·
    사례 중간 턴의 평서문은 반응을 붙이는 턴에만 한 문장 남긴다(직전 답과 내용 낱말이 다섯 이상 겹치거나 열두 어절을 넘거나,
    이 영역에서 이미 나간 반응(prior_reacts)과 내용 낱말이 둘 이상 겹치면 그 문장도 지운다) ·
    마무리 턴은 모델이 쓴 것 가운데 이해 확인 한 문장과 확인 질문만 남기고, 그 사이에 고정 문구(notice — 하나만 더 확인한다는 말)를 넣는다.
    질문이 없으면 고정 문구도 넣지 않는다(기록 parts: 갖춘 토막 — '123' = 이해 확인·고정 문구·질문).
    (P16-1d) 묻는 꼴이 아닌 끝('…궁금해요?', '…여쭤볼게요?')에 붙은 물음표는 마침표로 고친다."""
    from diag_project.services.turn_checks import finish_sentence_marks, receive_shared_words, strip_lead_address_q
    info: dict = {}
    raw0 = (text or "").strip()
    raw, n_mark = finish_sentence_marks(raw0)
    raw, n_ann = _ANNOUNCE_Q_RE.subn(r"\1.", raw)
    if n_mark + n_ann:
        info["mark_fix"] = n_mark + n_ann
    unlabeled = _LABEL_RE.sub(r"\1", raw)
    if unlabeled != raw:
        info["label"] = 1
    t = strip_lead_address_q(re.sub(r"(^|(?<=[.?!…]\s))리더님,\s*", "", unlabeled))
    if t != unlabeled:
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
            if len(stmts[0].split()) > REACT_MAX_EOJEOL:
                cut.append("long")
                stmts = []
            elif len(receive_shared_words(stmts[0], last_answer or "")) >= REACT_SHARED_MAX:
                cut.append("overlap")
                stmts = []
            elif any(len(receive_shared_words(stmts[0], old)) >= REACT_REPEAT_MAX for old in (prior_reacts or [])):
                cut.append("repeat")
                stmts = []
        if cut:
            info["react_cut"] = cut
        info["react"] = int(bool(stmts))
        if stmts:
            info["react_text"] = stmts[0]
    elif mode == "wrap":
        # 모델이 쓴 것에서 남기는 것 = 이해했다는 말로 맺은 문장(없으면 첫 평서문) + 질문. 그 사이에 고정 문구를 넣는다(질문이 있을 때만).
        first = next((x for x in stmts if "이해" in x), stmts[0] if stmts else None)
        if len(stmts) > (1 if first else 0):
            info["wrap_cut"] = len(stmts) - (1 if first else 0)
        put = notice if (q and notice) else None
        stmts = [x for x in (first, put) if x]
        info["parts"] = ("1" if first else "") + ("2" if put else "") + ("3" if q else "")
    if had_q and not q:
        info["q_lost"] = 1
    return " ".join(stmts + q).strip(), info


def question_issue(text: str | None, prev_coach: list[str] | str | None, *, mode: str = "mid", beyond_ok: bool = True) -> str | None:
    """질문 꼴에서 한 번 다시 쓰게 할 것 — permit(허락을 구하는 끝맺음) | two(한 문장에 물음 둘) | alt(둘 중 고르기) | yesno(예·아니오) |
    long(마무리 턴의 확인 질문이 열다섯 어절 초과) | request(마무리 턴의 확인 질문이 청하는 말·궁금하다는 말로 끝남) |
    same_end(앞의 두 코치 턴 가운데 하나와 끝 두 어절이 같다). 없으면 None.
    마무리 턴은 확인 질문이라 alt·yesno 를 보지 않는다(P16-1b). long·request 는 마무리 턴에서만 본다(P16-1c).
    (P16-1d) beyond — 마무리 턴에서 팀 밖으로 이어졌는지를 물었는데 그 물음을 쓸 수 없는 턴이다(beyond_ok=False).
    request 에는 묻겠다고 알리는 끝('…여쭤볼게요', '…여쭙겠습니다')도 든다."""
    from diag_project.services.turn_checks import _FP_ASK_FOR_RE, _FP_WH_RE, is_announce_ask, is_request_ending
    q = next((x.strip() for x in reversed(split_sentences(text or "")) if x.strip() and is_question(x)), "")
    if not q:
        return None
    if mode == "wrap" and not beyond_ok and _BEYOND_RE.search(q):
        return "beyond"
    if _PERMIT_END_RE.search(q):
        return "permit"
    alt = bool(_ALT_RE.search(q))      # 둘 중 고르기는 물음 하나로 본다 — 사례 중간 턴에서는 alt 로 다시 쓰고, 마무리 턴에서는 그대로 둔다
    if alt and mode != "wrap":
        return "alt"
    if not alt and two_asks(q):
        return "two"
    if mode == "wrap":
        if len(q.split()) > WRAP_Q_MAX_EOJEOL:
            return "long"
        if is_request_ending(q) or is_announce_ask(q):
            return "request"
    elif not _FP_WH_RE.search(q) and not _FP_ASK_FOR_RE.search(q):
        return "yesno"
    prevs = [prev_coach] if isinstance(prev_coach, str) else list(prev_coach or [])
    key = end_key(text)
    if key and any(key == end_key(p) for p in prevs[-PREV_END_TURNS:] if p):
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
    # 누설 검사 — 안쪽 낱말(가드 사전)·칸 이름·진행 상태를 알리는 말. 마무리 턴은 이해한 것을 간추리고 마지막으로 하나를 더 확인하는 턴이라
    #   _WRAP_PASS_RE 에 드는 말만 누설로 보지 않는다(p16v2: '아직 듣지 못한 것'에 두 건, p16v2b: 간추린 문장의 '지연 없음'에 한 건이 통째로 떨어졌다).
    hits = [h for h in find_leaks(t, list(leader_texts or []), strict=True) if not (mode == "wrap" and _WRAP_PASS_RE.search(h))]
    if hits or find_state_leak(t) or (mode == "mid" and find_state_report(t)):
        return False, "leak"
    return True, "ok"


async def render(llm, *, mode: str, chapter: str, sub_name: str | None, case: list[tuple[str, str]], coach_said: list[str], missing: list[str],
                 persona_name: str | None, trace: list | None = None, meta: dict | None = None, mid_n: int = 0,
                 prior_reacts: list[str] | None = None, beyond_ok: bool = True) -> tuple[str | None, str]:
    """(코치 턴 | None, 기록). 기록 'llm' | 'llm_retry' | 'llm_first'(다시 쓴 것이 떨어져 처음 것을 씀) | 'stub' | 'miss:<사유>'.
    호출 오류·확인 탈락·질문 꼴(question_issue) 가운데 무엇이든 걸리면 한 번만 다시 부른다(턴당 합쳐 한 번).
    다시 쓴 것에 질문 꼴이 남아 있으면 그대로 쓴다(meta['left']). meta 에는 다듬은 기록(tidy)과 다시 쓴 까닭(rewrite)을 남긴다.
    mid_n — 이 사례에서 이미 나간 중간 턴 수(반응을 붙일지·팀 쪽 물음을 고를 수 있는지 정하는 순번, 호출자가 원장에서 읽어 넘긴다).
    prior_reacts — 이 영역에서 이미 나간 반응 문장들(같은 말을 되풀이한 반응을 지우는 데 쓴다). 붙은 반응은 meta['react_text'] 로 돌려준다.
    beyond_ok — 마무리 턴에서 팀 밖으로 이어졌는지를 물어도 되는가(영역당 BEYOND_MAX 번 — 호출자가 원장에서 세어 넘긴다).
    안 되는데 다시 쓴 뒤에도 그 물음이 남으면 질문을 지우고 이해 확인만 돌려준다(호출자가 바로 닫는다). 나간 질문이 팀 밖을 물었으면 meta['beyond']=1."""
    meta = meta if meta is not None else {}
    if os.getenv("FM_LLM_STUB"):
        return None, "stub"
    if llm is None or not case:
        return None, "miss:no_llm" if llm is None else "miss:no_material"
    react = mode == "mid" and reaction_allowed(mid_n)
    meta["react_slot"] = int(react)
    system = build_system(mode, persona_name, react=react, team_q=team_question_allowed(mid_n), beyond_ok=beyond_ok)
    notice = pick_notice(persona_name, coach_said) if mode == "wrap" else None
    leader_texts = [t for r, t in case if r == "user"]
    last_answer = leader_texts[-1] if leader_texts else ""
    prev_coach = list(coach_said or [])[-PREV_END_TURNS:]
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
        text, info = tidy(clean(out), mode=mode, react=react, last_answer=last_answer, prior_reacts=prior_reacts, notice=notice)
        ok, why = check(text, mode=mode, persona_name=persona_name, leader_texts=leader_texts)
        if not ok and why == "leak" and info.get("react_text"):
            # (P16-1d) 반응 문장이 누설 검사에 걸렸으면 턴 전체가 아니라 그 문장만 지운다(p16v2d Ella: 반응의 한마디 때문에 턴이 종전 경로로 넘어갔다)
            bare = text[len(info["react_text"]):].strip()
            ok2, why2 = check(bare, mode=mode, persona_name=persona_name, leader_texts=leader_texts)
            if ok2:
                text, ok, why = bare, True, "ok"
                info = {k: v for k, v in info.items() if k != "react_text"}
                info["react"] = 0
                info["react_cut"] = list(info.get("react_cut") or []) + ["leak"]
        if ok and info.get("q_lost"):
            ok, why = False, "no_question"
        if not ok:
            if trace is not None:
                trace.append([f"coach_v2:{mode}", why, text[:200]])
            continue
        issue = question_issue(text, prev_coach, mode=mode, beyond_ok=beyond_ok)
        if issue and attempt == 0:
            first = (text, info, issue)
            note = RETRY_NOTES[issue]
            meta["rewrite"] = issue
            if trace is not None:
                trace.append([f"coach_v2:{mode}", f"rewrite:{issue}", text[:200]])
            continue
        return _finish(text, info, issue, "llm_retry" if attempt else "llm", meta, mode)
    if first:
        # 다시 쓴 것이 확인에서 떨어졌다 — 처음 쓴 것(질문 꼴만 걸린 것)을 쓴다. 종전 경로로 넘기지 않는다.
        return _finish(first[0], first[1], first[2], "llm_first", meta, mode)
    return None, f"miss:{why}"


def _finish(text: str, info: dict, issue: str | None, how: str, meta: dict, mode: str) -> tuple[str | None, str]:
    """render 의 마지막 정리 — 기록을 채우고, 마무리 턴에서 쓸 수 없는 팀 밖 물음이 남았으면 질문을 지운다(이해 확인만 남는다)."""
    meta.update(info)
    if issue == "beyond":
        kept = [x.strip() for x in split_sentences(text) if x.strip() and not is_question(x) and x.strip() not in sum(WRAP_NOTICES.values(), ())]
        meta["beyond_dropped"] = 1
        meta["parts"] = "1" if kept else ""
        if not kept:
            return None, "miss:beyond"
        return kept[0], how
    if issue:
        meta["left"] = issue
    if mode == "wrap" and asks_beyond(text):
        meta["beyond"] = 1
    return text, how
