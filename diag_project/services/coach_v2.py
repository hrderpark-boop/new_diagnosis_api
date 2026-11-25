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

(2026-11-24 P16-1e 판정) 2코치 p16v2e: 마무리 턴 반복은 해결. 마지막 다듬기 네 가지 — ① 마무리 질문의 대상은 코드가 정해 넘긴다(wrap_target):
  결과 칸이 안 찼으면 결과 · 결과가 찼고 이 영역의 팀 밖 질문이 두 번 미만이면 팀 밖(옮길 것이 없으면 팀의 방식을 물어도 된다) · 두 번을 채웠으면 팀의 방식
  ② 이해 확인이 두 문장이면 둘 다 남기고, 세 문장 이상이면 '이해'가 든 문장과 그 앞 문장만. 문장 머리의 '이번 사례에서/이 사례에서'는 뗀다
  ③ 확인 질문이 '-는지 + 청하는 말·알리는 말'로 끝나면 직접 묻는 꼴로 바꾼다(turn_checks.request_to_direct — to_direct)
  ④ 두 물음 판별이 '확인하고 싶습니다'의 '확인하고'를 이음 어미로 잡던 오류를 고쳤다(보조 용언 앞의 '-고'는 잇는 말이 아니다).

(2026-11-25 P16-2) 11/25 운영(1390071, FM_COACH_V2=1) Lucas 조직관리 실세션 — 사용자 판정: 변화가 체감되지 않는다 · 앵무새처럼 똑같이 되풀이한다 ·
  마무리 이해 확인이 지나치게 길고 나열식이다. 사례 중간 턴 10개 가운데 9개가 질문이 아닌 말(답을 옮긴 반응·앞 절)로 시작했고, 팀 밖 물음이 한 사례에 2~4번 나갔다.
  ① 되받기 제거 — 반응은 리더가 쓰지 않은 말로 여덟 어절 이하(직전 답과 내용 낱말 셋 이상 겹치면 지운다 — P16-1b 에서 다섯으로 늦췄던 것을 되돌렸다),
     들은 말을 전하는 꼴('-다고 들었다/하셨다')은 반응으로도 질문 앞 절로도 쓰지 않는다. 질문 안에서 리더 답을 옮긴 부분은 여섯 어절 이하
     (turn_checks.borrowed_run — P15b 기준). 넘으면 한 번 다시 쓰고, 그래도 넘으면 앞 절을 뗀다
  ② 같은 것을 두 번 묻지 않는다 — 팀의 방식이 됐는지·팀 밖으로 이어졌는지는 사례당 한 번씩(중간 턴과 마무리 턴을 합쳐, 낱말 기준 — asked_kinds).
     중간 턴에서 물었으면 마무리 대상에서 빠진다. 물을 것이 남지 않으면 마무리 턴을 내지 않는다(호출자가 넘김말로 다음 주제로 간다)
  ③ 마무리 턴의 이해 확인은 한 문장 · 스무 어절 이하 · 쉼표나 이음 어미로 세 토막 이상 잇지 않는다. 한 번 다시 쓰고, 그래도 길면 이해 확인을 빼고
     [고정 알림 문구 + 확인 질문]만 낸다. 두 문장 허용(P16-1e)은 철회했다
  ④ 영역 정의 답의 받는 말은 리더 문장을 옮기지 않는 한마디 요지로(열다섯 어절 이하 — render_align_gist). 라포의 받는 말 쪽은 routes/diagnoses.py.

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
    if not ep or ep.get("wrap_asked") or ep.get("wrap_skip"):
        return False
    if int(ep.get("leader_turns") or 0) + 1 >= _turn_cap(ep):
        return True
    rem = B.remaining(store, chapter)
    return rem - 1 <= 0 or (bool(all_subs) and rem - 1 <= B.reserve_turns(store, chapter, list(all_subs or [])))


def can_extend(ep: dict | None, store: dict | None, chapter: str | None, all_subs: list[str] | None) -> bool:
    """상태 기계가 지금 닫으려는 사례(여섯 가지가 다 나왔거나 진전이 없다)에 마무리 턴 한 번을 더 쓸 수 있는가 —
    사례 턴 상한과 영역 예산·미질문 예약 안에서만(세션 길이를 늘리지 않는다)."""
    from diag_project.services import bei_engine as B
    if not ep or ep.get("wrap_asked") or ep.get("wrap_skip") or not B.filled_slots(ep):
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


def build_system(mode: str, persona_name: str | None, *, react: bool = False, team_q: bool = True, target: str = "beyond",
                 asked: tuple[str, ...] | list[str] | set[str] = ()) -> str:
    """react — 사례 중간 턴에서 이번 턴에 반응 한 문장을 붙이는가(코드가 정해 넘긴다). 마무리 턴에서는 쓰지 않는다.
    team_q — 사례 중간 턴에서 팀의 방식이 됐는지·팀 밖으로 이어졌는지를 고를 수 있는 턴인가(그 사례의 세 번째 중간 턴부터 — team_question_allowed).
    target — 마무리 턴에서 물을 것(코드가 정한다 — wrap_target): 'result'(결과) | 'beyond'(팀 밖으로 이어졌는지) | 'team'(팀의 방식이 됐는지).
    asked — (P16-2) 이 사례에서 이미 물은 것('team' · 'beyond'). 물은 것은 고를 수 있는 물음에서 뺀다."""
    asked = set(asked or ())
    from diag_project.services.persona_register import register_hint
    head = ("당신은 경험 많은 역량 면접관입니다. 목적은 이 사례에서 리더가 실제로 한 행동·판단·결과를 수준을 가릴 수 있을 만큼 듣는 것입니다.\n\n")
    voice = f"[말투] {register_hint(persona_name)} 리더를 부를 때는 '리더님'이라고만 한다."
    if mode == "wrap":
        ask = {
            "result": "- 이 일의 결과나 끝이 어떻게 됐는지를 묻는다.\n",
            "beyond": ("- 그 방식이 팀 밖(다른 부서·전사·외부)으로 이어졌는지를 묻는다.\n"
                       + ("- 리더가 이 일에서 남에게 옮길 수 있는 기준·절차·양식·도구를 만들지 않았다면 묻지 않는다(첫째 토막만 쓴다). "
                          "그 방식이 팀에 자리 잡았는지는 이미 물었으므로 다시 묻지 않는다.\n" if "team" in asked else
                          "- 리더가 이 일에서 남에게 옮길 수 있는 기준·절차·양식·도구를 만들지 않았다면, 그 대신 그 방식이 팀의 운영 방식이 됐는지를 물어도 된다.\n")),
            "team": ("- 그 방식이 팀의 운영 방식이 됐는지를 묻는다.\n"
                     "- 팀 밖으로 이어졌는지는 이 턴에서 묻지 않는다.\n"),
        }[target if target in ("result", "beyond", "team") else "beyond"]
        return (
            head.replace("이 사례에서", "이 일에서")      # 마무리 턴 지시문에는 '사례'라는 낱말을 쓰지 않는다(모델이 '이 사례에서 …'로 옮겨 써 린트에 걸렸다 — p16v2d)
            + "이 턴은 지금 듣고 있는 일에 대해 코치가 하는 마지막 말입니다. 두 토막을 이 순서로 씁니다.\n\n"
            "[첫째 토막]\n"
            "- 리더가 이 일에서 한 것의 요지만 한 문장, 스무 어절 이하로 적고, 코치가 그렇게 이해했다는 말로 맺는다. 확실히 들었다고 단정하지 않는다.\n"
            "- 한 일을 차례로 늘어놓지 않는다. 쉼표나 이음말로 여러 토막을 잇지 않고, 가장 큰 줄기 하나만 적는다.\n"
            "- 리더가 한 말로만 쓴다. 평가·칭찬·짐작을 보태지 않는다.\n\n"
            "[둘째 토막]\n"
            "- 아직 확인되지 않은 것 하나를 짧게 묻는 질문 한 문장(열다섯 어절 이하). 이야기를 넓게 청하는 질문이 아니라 빠진 것을 확인하는 질문이다. "
            "예·아니오로 답할 수 있는 꼴이어도 된다.\n"
            "- 물음은 하나다. 한 문장에 두 가지를 이어 묻지 않는다.\n"
            "- 묻는 말로 끝낸다. 말해 달라고 청하는 말이나 궁금하다는 말, 묻겠다고 알리는 말, 해 줄 수 있는지 허락을 구하는 말로 끝내지 않는다. "
            "앞의 두 코치 턴과 같은 말로 끝내지 않는다.\n\n"
            "[무엇을 묻는가]\n"
            + ask
            + "- 리더가 이미 답한 것, 모른다거나 기억나지 않는다고 답한 것은 묻지 않는다. 이미 들은 것을 다시 확인하지 않는다.\n"
            "- 그래서 물을 것이 없으면 첫째 토막만 쓰고 끝낸다. 닫는다거나 다음으로 넘어간다는 말은 쓰지 않는다.\n\n"
            "[그 밖]\n"
            "- 두 토막 밖의 문장은 쓰지 않는다. 하나만 더 확인하겠다고 알리는 말은 두 토막 사이에 따로 들어가므로 쓰지 않는다. "
            "무엇을 듣지 못했는지 늘어놓지 않는다.\n"
            "- 토막의 이름·번호·머리말·따옴표는 쓰지 않는다.\n"
            + _BAN_BASE + _BAN_INNER + "\n" + voice
        )
    # (P16-2) 질문 앞머리 — 반응을 붙이는 턴이든 아니든 같다. 11/25 운영: 반응이 없는 턴에서 답을 앞 절로 옮겨 시작했다(그 턴의 지시문에는 이 줄이 없었다)
    no_echo = ("- 질문은 묻는 말로 바로 시작한다. 리더의 답을 앞 절로 옮겨 놓고 시작하지 않는다. "
               "들은 것을 다시 전하는 말(그렇게 들었다는 말, 리더가 그렇게 말했다는 말)로 시작하지 않는다.\n"
               "- 리더의 답에서 가져오는 말은 가리킬 낱말 하나면 된다.\n")
    shape = (
        "[이번 턴의 꼴]\n"
        "- 반응 한 문장을 먼저 쓰고, 이어서 질문 한 문장을 쓴다. 아래 조건대로 반응을 쓸 수 없으면 반응 없이 질문만 쓴다.\n"
        + no_echo
        + "- 그 밖의 설명·머리말·번호·따옴표는 쓰지 않는다.\n\n"
        "[반응]\n"
        "- 여덟 어절 이하 한 문장. 상황의 어려움을 알아주거나 답의 뜻을 한마디로 짚는다.\n"
        "- 리더가 쓰지 않은 말로 쓴다. 리더의 답을 옮겨 적거나 줄여 적지 않는다.\n"
        "- 칭찬하지 않는다. 리더가 한 일이나 결과에 값을 매기는 말을 쓰지 않는다.\n"
        "- 무엇이 드러났고 무엇이 아직 남았는지를 말로 풀어 설명하지 않는다.\n\n"
    ) if react else (
        "[이번 턴의 꼴]\n"
        "- 질문 한 문장만 쓴다. 반응·받는 말·간추림 같은 다른 문장은 붙이지 않는다.\n"
        + no_echo
        + "- 그 밖의 설명·머리말·번호·따옴표는 쓰지 않는다.\n\n"
    )
    # (P16-2) 팀의 방식이 됐는지·팀 밖으로 이어졌는지는 사례당 한 번씩 — 이미 물은 것은 고를 수 있는 물음에서 뺀다
    free = [x for x in ("team", "beyond") if x not in asked]
    team_line = {
        ("team", "beyond"): "- 그 방식이 팀의 운영 방식이 됐는지, 팀 밖(다른 부서·전사·외부)으로 이어졌는지.\n",
        ("team",): "- 그 방식이 팀의 운영 방식이 됐는지. 팀 밖으로 이어졌는지는 이 일에서 이미 물었으므로 다시 묻지 않는다.\n",
        ("beyond",): "- 그 방식이 팀 밖(다른 부서·전사·외부)으로 이어졌는지. 팀에 자리 잡았는지는 이 일에서 이미 물었으므로 다시 묻지 않는다.\n",
    }.get(tuple(free))
    pick = (
        "[질문 고르기]\n"
        "- 지금까지 들은 것 가운데 가장 덜 드러난 것 하나를 묻는다 — 리더 본인의 구체 행동, 그렇게 판단한 까닭, 결과의 크기, 팀원에게 어떻게 했는지, "
        + ("그 방식이 이후 팀에 남았는지, " if "team" in free else "") + "사례가 어떻게 끝났는지.\n"
        + team_line + "\n"
    ) if (team_q and team_line) else (
        "[질문 고르기]\n"
        "- 지금까지 들은 것 가운데 가장 덜 드러난 것 하나를 묻는다 — 리더 본인의 구체 행동, 그렇게 판단한 까닭, 결과의 크기, 팀원에게 어떻게 했는지, "
        "사례가 어떻게 끝났는지.\n"
        "- 그 방식이 팀에 자리 잡았는지, 팀 밖으로 이어졌는지는 이 일에서 이미 물었다. 다시 묻지 않는다.\n\n"
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
REACT_SHARED_MAX = 3               # 반응 문장이 직전 답과 겹치는 내용 낱말이 이 수 이상이면 그 문장을 지운다(P16-2 — P16-1b 에서 5로 늦췄던 것을 되돌렸다)
REACT_MAX_EOJEOL = 8               # 반응 문장은 여덟 어절 이하 — 넘으면 그 문장을 지운다(P16-2 — 종전 12)
SUMMARY_MAX_EOJEOL = 20            # (P16-2) 마무리 턴의 이해 확인은 한 문장 스무 어절 이하
SUMMARY_MAX_PARTS = 2              # (P16-2) 이해 확인을 쉼표·이음 어미로 이은 토막이 이 수를 넘으면(세 토막 이상) 탈락
ALIGN_GIST_MAX_EOJEOL = 15         # (P16-2) 영역 정의 답의 받는 말(한마디 요지)은 열다섯 어절 이하
ALIGN_GIST_BORROW_MAX = 3          # (P16-2) 그 받는 말에서 리더 문장을 그대로 옮긴 부분은 이어진 세 어절까지
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
# (P16-2) 낱말을 넓혔다 — '다른 교육팀'·'다른 과정'·'운영부서'·'공식 기준'도 팀 밖 물음으로 센다(11/25 운영: 이 말들로 같은 것을 다시 물었다)
_BEYOND_RE = re.compile(r"팀\s*(밖|바깥)|(다른|타)\s*[가-힣]{0,4}\s*(부서|팀(?!원)|과정)|운영\s*부서|전사|외부|공식\s*[가-힣 ]{0,6}기준")
# (P16-2) 그 방식이 팀의 방식이 됐는지를 묻는 말
_TEAM_RE = re.compile(r"자리\s*잡|정착|팀의\s*[가-힣 ]{0,8}(방식|기준|양식|절차|규칙|원칙|표준)|팀이\s*쓰는|팀에\s*남|팀\s*안에서\s*(계속|이어)")
# (P16-2) 들은 말을 전하는 꼴 — '…다고 들었습니다', '…라고 하셨는데', '…다는 말씀이군요'
_HEARD_RE = re.compile(r"(다고|라고)\s*(들었|하셨|말씀하셨)|(다는|라는)\s*말씀")
# (P16-2) 쉼표로 질문 앞에 붙여 쓴 반응 — '…정하셨군요, 그 과제들이 …' → 반응 문장으로 갈라 반응 규칙을 그대로 건다
_GLUED_REACT_RE = re.compile(r"^(?P<a>[^,，?.!]{4,}?(?:군요|네요|습니다|어요|아요|지요|죠))[,，]\s+(?P<b>\S.+)$")
# (P16-2) 이해 확인의 토막을 잇는 어절 — 쉼표로 끝나거나 이음 어미('-고', '-며')로 끝난 어절. 말을 전하는 '-라고/-다고'와 '그리고'는 세지 않는다
_JOIN_TOK_RE = re.compile(r"[,，]$|[가-힣](고|며)[,，]?$")
_JOIN_SKIP_RE = re.compile(r"(라고|다고|냐고|자고|그리고|하고는|최고|보고서)[,，]?$")
# (P16-1d) 묻겠다고 알리는 말에 붙은 물음표 — 마침표로 고친다('…궁금해요?'는 turn_checks.finish_sentence_marks 가 고친다)
_ANNOUNCE_Q_RE = re.compile(r"(여쭤볼게요|여쭤보겠습니다|여쭙겠습니다|물어볼게요|묻겠습니다)\?")
# (P16-1e) 문장 머리의 '이번 사례에서 / 이 사례에서' — 마무리 턴에서 뗀다
_CASE_HEAD_RE = re.compile(r"(^|(?<=[.?!…]\s))(?:이번|이)\s*사례에서(?:는)?[,，]?\s*")
# (P16-1e) 확인 질문의 끝 — '-는지/-인지' 뒤에 온 알리는 말·궁금하다는 말(turn_checks.request_to_direct 가 다루지 않는 끝말도 여기서 받는다)
_ASK_TAIL_RE = re.compile(r"^(?P<body>.*[가-힣](?:는지|인지))(?:를|가|도)?[,，]?\s*"
                          r"(?:여쭤볼게요|여쭤보겠습니다|여쭙겠습니다|물어볼게요|궁금[가-힣]+|확인하고\s*싶[가-힣]+|알고\s*싶[가-힣]+|여쭤(?:봐)?도\s*[가-힣]+)[?.!…\s]*$")
RETRY_NOTES = {
    "permit": "앞서 쓴 질문은 허락을 구하는 말로 끝났다. 무엇을·어떻게·왜를 직접 묻는 말로 끝낸다.",
    "alt": "앞서 쓴 질문은 둘 가운데 고르게 했다. 고르게 하지 말고 열어서 묻는다.",
    "yesno": "앞서 쓴 질문은 예·아니오로 답할 수 있었다. 무엇을·어떻게·왜로 묻는다.",
    "same_end": "앞서 쓴 문장은 앞의 코치 턴과 같은 말로 끝났다. 끝맺는 말을 바꾼다.",
    "two": "앞서 쓴 질문은 한 문장에 두 가지를 물었다. 하나만 묻는다.",
    "long": "앞서 쓴 확인 질문은 길었다. 열다섯 어절 이하로 하나만 묻는다.",
    "request": "앞서 쓴 확인 질문은 청하는 말이나 궁금하다는 말, 묻겠다고 알리는 말로 끝났다. 묻는 말로 끝낸다.",
    "beyond": "앞서 쓴 확인 질문은 팀 밖으로 이어졌는지를 물었다. 그 물음은 이 턴에서 쓰지 않는다. 결과나 팀의 방식 쪽에서 아직 듣지 못한 것을 묻고, 없으면 첫째 토막만 쓴다.",
    # (P16-2)
    "again": "앞서 쓴 질문은 이 일에서 이미 물은 것(그 방식이 팀에 자리 잡았는지, 팀 밖으로 이어졌는지)을 다시 물었다. 그 물음은 쓰지 않고 아직 묻지 않은 다른 것을 묻는다.",
    "borrow": "앞서 쓴 질문은 리더의 답을 길게 옮긴 절로 시작했다. 옮긴 절 없이 묻는 말로 바로 시작한다.",
    "heard": "앞서 쓴 질문은 들은 것을 다시 전하는 말로 시작했다. 그 말 없이 묻는 말로 바로 시작한다.",
    "sum_long": "앞서 쓴 첫째 토막은 길었다. 요지만 한 문장, 스무 어절 이하로 쓴다.",
    "sum_parts": "앞서 쓴 첫째 토막은 한 일을 여러 토막으로 이어 늘어놓았다. 가장 큰 줄기 하나만 한 문장, 스무 어절 이하로 쓴다.",
}


def wrap_target(result_filled: bool, beyond_n: int, asked: tuple[str, ...] | list[str] | set[str] = ()) -> str | None:
    """(P16-1e) 마무리 턴에서 물을 것을 코드가 정한다 — 그 사례의 결과 칸이 안 찼으면 'result' ·
    결과가 찼고 이 영역에서 팀 밖을 물은 마무리 질문이 BEYOND_MAX 번 미만이면 'beyond' · 다 채웠으면 'team'.
    (P16-2) 이 사례에서 이미 물은 것(asked — 중간 턴 포함)은 대상에서 뺀다. 남은 것이 없으면 None(마무리 턴을 내지 않는다)."""
    asked = set(asked or ())
    if not result_filled:
        return "result"
    if "beyond" not in asked and int(beyond_n or 0) < BEYOND_MAX:
        return "beyond"
    return "team" if "team" not in asked else None


def asked_kinds(text: str | None) -> set[str]:
    """(P16-2) 이 코치 말의 질문이 묻는 것 — 'team'(그 방식이 팀의 방식이 됐는지) · 'beyond'(팀 밖으로 이어졌는지). 낱말 기준, 질문 문장만 본다."""
    qs = [x for x in split_sentences(text or "") if x.strip() and is_question(x)]
    out: set[str] = set()
    if any(_BEYOND_RE.search(x) for x in qs):
        out.add("beyond")
    if any(_TEAM_RE.search(x) for x in qs):
        out.add("team")
    return out


def summary_parts(sentence: str | None) -> int:
    """(P16-2) 이해 확인 문장이 몇 토막으로 이어졌는가 — 쉼표나 이음 어미('-고', '-며', '-으며')로 끝난 어절마다 한 토막이 는다.
    보조 용언 앞의 '-고'('하고 있다')와 말을 전하는 '-라고'는 세지 않는다."""
    toks = (sentence or "").split()
    n = 1
    for i, tok in enumerate(toks[:-1]):
        if not _JOIN_TOK_RE.search(tok) or _JOIN_SKIP_RE.search(tok):
            continue
        if not tok.rstrip().endswith((",", "，")) and toks[i + 1].startswith(("있", "싶", "계", "나서", "나면", "난", "말")):
            continue
        n += 1
    return n


def summary_issue(body: list[str] | None) -> str | None:
    """(P16-2) 마무리 턴의 이해 확인(첫째 토막)에서 한 번 다시 쓰게 할 것 — sum_long(두 문장 이상이거나 스무 어절 초과) | sum_parts(세 토막 이상)."""
    body = [x for x in (body or []) if x.strip()]
    if not body:
        return None
    if len(body) > 1 or len(body[0].split()) > SUMMARY_MAX_EOJEOL:
        return "sum_long"
    return "sum_parts" if summary_parts(body[0]) > SUMMARY_MAX_PARTS else None


def wrap_summary(text: str | None) -> list[str]:
    """(P16-2) 다듬은 마무리 턴에서 이해 확인(첫째 토막)에 해당하는 문장들 — 질문과 고정 알림 문구를 뺀 평서문."""
    fixed = set(sum(WRAP_NOTICES.values(), ()))
    return [x.strip() for x in split_sentences(text or "") if x.strip() and not is_question(x) and x.strip() not in fixed]


def _last_question(text: str | None) -> str:
    return next((x.strip() for x in reversed(split_sentences(text or "")) if x.strip() and is_question(x)), "")


def echo_issue(text: str | None, last_answer: str | None) -> str | None:
    """(P16-2) 사례 중간 턴의 질문이 리더 답을 되받으며 시작하는가 — heard(들은 말을 전하는 절로 시작) | borrow(리더 답을 옮긴 부분이 여섯 어절 초과)."""
    from diag_project.services.turn_checks import BORROW_MAX_EOJEOL, borrowed_run, question_first_clause
    q = _last_question(text)
    if not q:
        return None
    if _HEARD_RE.search(question_first_clause(q) or ""):
        return "heard"
    return "borrow" if borrowed_run(q, last_answer or "") > BORROW_MAX_EOJEOL else None


def strip_front(text: str | None) -> str | None:
    """(P16-2) 질문의 앞 절을 뗀다 — '…적용하셨는데, 그때 무엇을 맞추셨습니까?' → '그때 무엇을 맞추셨습니까?'. 뗄 앞 절이 없거나
    남는 질문이 두 어절에 못 미치면 None(그대로 둔다)."""
    from diag_project.services.turn_checks import question_first_clause
    q = _last_question(text)
    front = question_first_clause(q) if q else ""
    if not front or not q.startswith(front):
        return None
    rest = q[len(front):].lstrip(" ,，")
    if len(rest.split()) < 2:
        return None
    t = (text or "").strip()
    return (t[:len(t) - len(q)] + rest).strip() if t.endswith(q) else None


def to_direct(question: str | None, *, formal: bool) -> str | None:
    """(P16-1e) '-는지 + 청하는 말·알리는 말'로 끝난 확인 질문을 직접 묻는 꼴로 — '…어땠는지 여쭙겠습니다.' → '…어땠습니까?'.
    바꾸는 일은 P15 의 turn_checks.request_to_direct 가 한다. 끝말을 코치 말투의 청하는 말로 맞춰 넘긴다(바꾼 문장이 코치 말투를 따르게).
    그 꼴이 아니면 None."""
    from diag_project.services.turn_checks import _DIRECT_RE, request_to_direct
    q = (question or "").strip()
    m = _DIRECT_RE.match(q)
    body = (m.group("head") + m.group("nj")) if m else None
    if body is None:
        m2 = _ASK_TAIL_RE.match(q)
        body = m2.group("body") if m2 else None
    if body is None:
        return None
    return request_to_direct(body + (" 말씀해 주시겠습니까?" if formal else " 말씀해 주시겠어요?"))


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
        if toks[i + 1].startswith(("싶", "있", "계", "나서", "나면", "난")):
            continue          # (P16-1e) '확인하고 싶습니다', '운영하고 있습니까' — 보조 용언 앞의 '-고'는 물음을 잇는 말이 아니다
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
         notice: str | None = None, formal: bool = True) -> tuple[str, dict]:
    """모델이 쓴 코치 말을 다듬는다 — (결과, 기록).
    문장 머리의 호칭과 안쪽 표지를 떼고 · 값 매기는 말이 든 문장을 지우고 · 질문은 첫 질문 하나만 남기고(그 뒤는 버린다) ·
    사례 중간 턴의 평서문은 반응을 붙이는 턴에만 한 문장 남긴다(직전 답과 내용 낱말이 다섯 이상 겹치거나 열두 어절을 넘거나,
    이 영역에서 이미 나간 반응(prior_reacts)과 내용 낱말이 둘 이상 겹치면 그 문장도 지운다) ·
    마무리 턴은 모델이 쓴 것 가운데 이해 확인 한 문장과 확인 질문만 남기고, 그 사이에 고정 문구(notice — 하나만 더 확인한다는 말)를 넣는다.
    질문이 없으면 고정 문구도 넣지 않는다(기록 parts: 갖춘 토막 — '123' = 이해 확인·고정 문구·질문).
    (P16-1d) 묻는 꼴이 아닌 끝('…궁금해요?', '…여쭤볼게요?')에 붙은 물음표는 마침표로 고친다.
    (P16-2) 사례 중간 턴: 쉼표로 질문 앞에 붙여 쓴 반응은 반응 문장으로 가른다 · 반응은 여덟 어절 이하, 직전 답과 내용 낱말 셋 이상 겹치거나
    들은 말을 전하는 꼴이면 지운다. 마무리 턴: 이해 확인 문장들은 그대로 남긴다(길이·토막 판별과 빼기는 render 가 한다 — wrap_summary)."""
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
    if mode == "wrap":
        uncased = _CASE_HEAD_RE.sub(r"\1", unlabeled)      # (P16-1e) 문장 머리의 '이번 사례에서 / 이 사례에서'
        if uncased != unlabeled:
            info["case_head"] = 1
            unlabeled = uncased
    t = strip_lead_address_q(re.sub(r"(^|(?<=[.?!…]\s))리더님,\s*", "", unlabeled))
    if t != unlabeled:
        info["addr"] = 1
    sents = [x.strip() for x in split_sentences(t) if x.strip()]
    if mode == "mid" and len(sents) == 1:
        m_glue = _GLUED_REACT_RE.match(sents[0])
        if m_glue:
            sents = [m_glue.group("a") + ".", m_glue.group("b")]
            info["glued"] = 1
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
            elif _HEARD_RE.search(stmts[0]):
                cut.append("heard")
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
        # 모델이 쓴 것에서 남기는 것 = 이해 확인(첫째 토막) + 질문. 그 사이에 고정 문구를 넣는다(질문이 있을 때만).
        # (P16-1e) 이해 확인이 두 문장이면 둘 다 남긴다 — p16v2e: '이해'가 든 뒤 문장만 남겨 내용이 빠진 첫째 토막이 나갔다.
        #   세 문장 이상이면 '이해'가 든 문장과 그 바로 앞 문장만. 모델이 쓴 알림 문장(하나만 더 확인한다는 말)은 지운다.
        # (P16-2) 이해 확인은 한 문장이어야 한다 — 여기서는 모델이 쓴 문장을 그대로 두고 기록(sum)에 적는다. 두 문장 이상·스무 어절 초과·세 토막 이상이면
        #   render 가 한 번 다시 쓰게 하고, 그래도 그러면 이해 확인을 빼고 [고정 문구 + 확인 질문]만 낸다.
        body = [x for x in stmts if not _NOTICE_RE.search(x)]
        if len(body) != len(stmts):
            info["wrap_cut"] = len(stmts) - len(body)
        if q:
            direct = to_direct(q[0], formal=formal)      # (P16-1e) '-는지 + 청하는 말·알리는 말' → 직접 묻는 꼴
            if direct and direct != q[0]:
                q = [direct]
                info["direct_fix"] = 1
        put = notice if (q and notice) else None
        stmts = body + ([put] if put else [])
        info["parts"] = ("1" if body else "") + ("2" if put else "") + ("3" if q else "")
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
                 prior_reacts: list[str] | None = None, result_filled: bool = True, beyond_n: int = 0,
                 asked: tuple[str, ...] | list[str] | set[str] = ()) -> tuple[str | None, str]:
    """(코치 턴 | None, 기록). 기록 'llm' | 'llm_retry' | 'llm_first'(다시 쓴 것이 떨어져 처음 것을 씀) | 'stub' | 'skip:none_left' | 'miss:<사유>'.
    호출 오류·확인 탈락·다시 쓸 것(turn_issues) 가운데 무엇이든 걸리면 한 번만 다시 부른다(턴당 합쳐 한 번 — 걸린 것이 여럿이면 사유를 함께 넘긴다).
    다시 쓴 것에 남은 것은 코드로 정리한다(_finish): 앞 절 떼기 · 이해 확인 빼기 · 이미 물은 것을 다시 묻는 마무리 턴은 내지 않는다. 그 밖의 질문 꼴은 그대로 쓴다(meta['left']).
    mid_n — 이 사례에서 이미 나간 중간 턴 수(반응을 붙일지·팀 쪽 물음을 고를 수 있는지 정하는 순번, 호출자가 원장에서 읽어 넘긴다).
    prior_reacts — 이 영역에서 이미 나간 반응 문장들(같은 말을 되풀이한 반응을 지우는 데 쓴다). 붙은 반응은 meta['react_text'] 로 돌려준다.
    result_filled · beyond_n — 마무리 턴에서 물을 것을 정하는 값(wrap_target): 그 사례의 결과 칸이 찼는가 · 이 영역에서 팀 밖을 물은 마무리 질문 수.
    asked — (P16-2) 이 사례에서 이미 물은 것('team' · 'beyond', 중간 턴과 마무리 턴을 합쳐 — 호출자가 원장에서 읽어 넘긴다). 마무리 턴에서 물을 것이
    남지 않으면 부르지 않고 (None, 'skip:none_left'). 나간 질문이 묻는 것은 meta['asks'], 정한 대상은 meta['target']."""
    meta = meta if meta is not None else {}
    if os.getenv("FM_LLM_STUB"):
        return None, "stub"
    if llm is None or not case:
        return None, "miss:no_llm" if llm is None else "miss:no_material"
    asked = set(asked or ())
    react = mode == "mid" and reaction_allowed(mid_n)
    meta["react_slot"] = int(react)
    from diag_project.services.intro_messages import line_register
    target = wrap_target(result_filled, beyond_n, asked) if mode == "wrap" else None
    if mode == "wrap" and target is None:
        meta["target"] = "none"
        return None, "skip:none_left"
    # 이 턴에서 쓸 수 없는 물음 — 이 사례에서 이미 물은 것(asked), 그리고 마무리 턴에서 영역당 횟수를 채운 팀 밖 물음(capped)
    capped = mode == "wrap" and int(beyond_n or 0) >= BEYOND_MAX
    formal = line_register(persona_name) == "formal"
    if target:
        meta["target"] = target
    system = build_system(mode, persona_name, react=react, team_q=team_question_allowed(mid_n), target=target or "beyond", asked=asked)
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
        text, info = tidy(clean(out), mode=mode, react=react, last_answer=last_answer, prior_reacts=prior_reacts, notice=notice, formal=formal)
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
        issues = turn_issues(text, info, prev_coach, mode=mode, last_answer=last_answer, banned=asked, capped=capped)
        if issues and attempt == 0:
            first = (text, info, issues)
            note = " ".join(RETRY_NOTES[i] for i in issues)
            meta["rewrite"] = "+".join(issues)
            if trace is not None:
                trace.append([f"coach_v2:{mode}", f"rewrite:{meta['rewrite']}", text[:200]])
            continue
        return _finish(text, info, issues, "llm_retry" if attempt else "llm", meta, mode)
    if first:
        # 다시 쓴 것이 확인에서 떨어졌다 — 처음 쓴 것(다시 쓸 것만 걸린 것)을 쓴다. 종전 경로로 넘기지 않는다.
        return _finish(first[0], first[1], first[2], "llm_first", meta, mode)
    return None, f"miss:{why}"


def turn_issues(text: str | None, info: dict | None, prev_coach: list[str] | str | None, *, mode: str, last_answer: str | None,
                banned: set[str] | None = None, capped: bool = False) -> list[str]:
    """(P16-2) 이 턴에서 한 번 다시 쓰게 할 것 전부 — 이 사례에서 이미 물은 것을 다시 물음(again) · 영역당 횟수를 채운 팀 밖 물음(beyond, 마무리 턴) ·
    마무리 턴의 이해 확인(sum_long | sum_parts) · 사례 중간 턴의 되받는 앞 절(heard | borrow) · 질문 꼴(question_issue 가 고른 하나). 걸린 순서대로."""
    out: list[str] = []
    kinds = asked_kinds(text)
    if set(banned or ()) & kinds:
        out.append("again")
    elif capped and "beyond" in kinds:
        out.append("beyond")
    if mode == "wrap":
        si = summary_issue(wrap_summary(text))
        if si:
            out.append(si)
    else:
        ei = echo_issue(text, last_answer)
        if ei:
            out.append(ei)
    qi = question_issue(text, prev_coach, mode=mode)
    if qi:
        out.append(qi)
    return out


def _finish(text: str, info: dict, issues: list[str] | str | None, how: str, meta: dict, mode: str) -> tuple[str | None, str]:
    """render 의 마지막 정리 — 기록을 채우고, 다시 쓴 뒤에도 남은 것을 코드로 정리한다.
    (P16-2) 마무리 턴이 이 사례에서 이미 물은 것(또는 영역당 횟수를 채운 팀 밖)을 다시 물으면 그 턴을 내지 않는다(None, 'miss:again' | 'miss:beyond') ·
    마무리 턴의 이해 확인이 여전히 길거나 여러 토막이면 이해 확인을 빼고 [고정 문구 + 확인 질문]만 ·
    사례 중간 턴의 질문이 여전히 되받는 앞 절로 시작하면 그 앞 절을 뗀다. 정리하지 못한 것은 meta['left']."""
    issues = [issues] if isinstance(issues, str) else list(issues or [])
    meta.update(info)
    body_s = wrap_summary(text) if mode == "wrap" else []
    if body_s:
        meta["sum_eojeol"] = sum(len(x.split()) for x in body_s)
        meta["sum_parts"] = max(summary_parts(x) for x in body_s)
    left = list(issues)
    for ai in ("again", "beyond"):
        if ai in left and mode == "wrap":
            meta["again_dropped"] = ai
            return None, f"miss:{ai}"
    for si in ("sum_long", "sum_parts"):
        if si in left and mode == "wrap":
            body = " ".join(body_s)
            if body and text.startswith(body):
                text = text[len(body):].strip()
                meta["sum_drop"] = si
                meta["parts"] = str(meta.get("parts") or "").replace("1", "")
                left.remove(si)
    for ei in ("heard", "borrow"):
        if ei in left and mode == "mid":
            cut = strip_front(text)
            if cut:
                text = cut
                meta["front_cut"] = ei
                left.remove(ei)
    if left:
        meta["left"] = "+".join(left)
    kinds = asked_kinds(text)
    if kinds:
        meta["asks"] = sorted(kinds)
    if mode == "wrap" and "beyond" in kinds:
        meta["beyond"] = 1
    return text, how


# ── (2026-11-25 P16-2) 초반 라포·영역 정의의 받는 말 — 리더의 말을 옮기지 않는다 ─────────────────────────────
#   11/25 운영 Lucas: '그냥 그래' → '그냥 그렇다고 말씀하셨습니다.' · 낱말 나열 답 → '{리더 답}, 알겠습니다.' ·
#   영역 정의 답 → 리더의 첫 문장을 그대로 옮기고 '…라고 하셨군요.' 새 방식이 켜져 있을 때만 아래를 쓴다(호출 쪽 routes/diagnoses.py).
RAPPORT_RECV_MAX_EOJEOL = 10       # 라포의 받는 말은 열 어절 이하


def rapport_receive_ok(sentence: str | None, answer: str | None) -> bool:
    """라포의 받는 말로 쓸 수 있는가 — 열 어절 이하 · 들은 말을 전하는 꼴('-다고 말씀하셨습니다')이 아니다 ·
    리더의 답을 옮기지 않았다(이어진 두 어절 이상을 옮기거나 내용 낱말이 둘 이상 겹치면 옮긴 것으로 본다). 아니면 호출자가 고정 받기를 쓴다."""
    from diag_project.services.turn_checks import borrowed_run, receive_shared_words
    s = (sentence or "").strip()
    if not s or len(s.split()) > RAPPORT_RECV_MAX_EOJEOL or _HEARD_RE.search(s) or re.search(r"말씀하셨|하셨다고", s):
        return False
    return borrowed_run(s, answer or "") < 2 and len(receive_shared_words(s, answer or "")) < 2


def build_align_gist_prompt(leader_answer: str, persona_name: str | None, note: str | None = None) -> str:
    ans = re.sub(r"\s+", " ", (leader_answer or "").strip())[-700:]
    return (
        "당신은 리더십 코치입니다. 리더가 이 영역을 어떤 일로 보는지 방금 답했습니다. 그 답을 한마디 요지로 받는 한 문장을 씁니다.\n\n"
        f"[리더의 답]\n{ans}\n\n"
        "[규칙]\n"
        "- 평서문 한 문장, 열다섯 어절 이하.\n"
        "- 리더의 문장을 그대로 옮기지 않는다. 길게 말한 것을 짧은 말로 줄여, 리더가 무엇을 가장 무겁게 보는지만 짚는다.\n"
        "- 리더가 그렇게 말했다고 전하는 꼴로 맺지 않는다. 리더가 그렇게 본다는 뜻으로, 끝은 -군요 또는 -네요 꼴로 맺는다.\n"
        "- 리더가 말하지 않은 내용은 넣지 않는다. 평가·칭찬·짐작을 보태지 않는다.\n"
        "- 묻지 않는다. 앞으로 무엇을 할지 알리지 않는다. 문장을 호칭으로 시작하지 않는다.\n"
        + (f"- 앞서 쓴 문장은 쓸 수 없었다 — {note} 그 점을 고쳐 새로 쓴다.\n" if note else "")
        + "\n출력: 그 한 문장만. 설명이나 따옴표를 붙이지 않는다."
    )


_GIST_NOTES = {"long": "열다섯 어절을 넘었다.", "borrow": "리더의 문장을 그대로 옮겼다.", "heard": "리더가 그렇게 말했다고 전하는 꼴이었다.",
               "question": "묻는 문장이었다.", "praise": "평가나 칭찬이 들어 있었다.", "leak": "쓸 수 없는 낱말이 들어 있었다.", "empty": "문장이 없었다."}


def check_align_gist(sentence: str | None, answer: str | None) -> tuple[bool, str]:
    """(통과, 사유: ok | empty | question | long | heard | borrow | praise | leak)."""
    from diag_project.services.leak_lexicon import find_leaks
    from diag_project.services.output_guard import find_praise, find_state_leak
    from diag_project.services.turn_checks import borrowed_run
    s = (sentence or "").strip()
    if not s:
        return False, "empty"
    if is_question(s):
        return False, "question"
    if len(s.split()) > ALIGN_GIST_MAX_EOJEOL:
        return False, "long"
    if _HEARD_RE.search(s) or re.search(r"(라고|다고)\s*(보|생각)?하셨|말씀하셨", s):
        return False, "heard"
    if borrowed_run(s, answer or "") > ALIGN_GIST_BORROW_MAX:
        return False, "borrow"
    if find_praise(s) or _EVAL_RE.search(s):
        return False, "praise"
    if find_leaks(s, [answer or ""], strict=True) or find_state_leak(s):
        return False, "leak"
    return True, "ok"


async def render_align_gist(llm, *, leader_answer: str | None, persona_name: str | None, trace: list | None = None) -> tuple[str | None, str]:
    """영역 정의 답의 받는 말 — 리더의 문장을 옮기지 않는 한마디 요지 한 문장(열다섯 어절 이하). (문장 | None, 기록 'llm' | 'llm_retry' | 'stub' | 'skip:empty' | 'miss:<사유>').
    확인에서 떨어지면 사유를 넘겨 한 번 다시 쓰고, 그래도 떨어지면 None(호출자가 고정 받기를 쓴다)."""
    from diag_project.services.receive_render import strip_lead_address
    from diag_project.services.turn_checks import fix_leader_address
    if not (leader_answer or "").strip():
        return None, "skip:empty"
    if os.getenv("FM_LLM_STUB"):
        return None, "stub"
    if llm is None:
        return None, "miss:no_llm"
    why, note = "empty", None
    for attempt in (0, 1):
        try:
            out = await llm._generate_with_retry(prompt=build_align_gist_prompt(leader_answer or "", persona_name, note), max_tokens=120,
                                                 thinking_budget=0, call_type="align_gist", temperature=0.4)
        except Exception as e:  # noqa: BLE001
            logger.warning("align gist render failed: %s", e)
            return None, "miss:error"
        ss = [x.strip() for x in split_sentences(clean(out)) if x.strip()]
        s = strip_lead_address(fix_leader_address(ss[0])) if ss else ""
        if s and s[-1] not in ".!?…":
            s += "."
        ok, why = check_align_gist(s, leader_answer)
        if ok:
            return s, ("llm_retry" if attempt else "llm")
        if trace is not None:
            trace.append(["align_gist", why, s[:200]])
        note = _GIST_NOTES.get(why, "쓸 수 없는 문장이었다.")
    return None, f"miss:{why}"
