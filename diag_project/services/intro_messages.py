"""진단 안내 등 표준 메시지 생성

LLM 이 가이드 텍스트를 학습 데이터 패턴으로 변형하는 문제를 방지하기 위해
표준 텍스트는 시스템이 직접 출력.
"""

import random
import re

from diag_project.data.competencies import (
    COMPETENCY_FRAMEWORK,
    SUBCOMPETENCY_ANCHORS,  # noqa: F401  (situation 서술 — 분석·게이트용, 호환 유지)
    get_anchor_questions,
)

# 5개 챕터의 진단 정의 (LLM 이 아닌 시스템이 직접 사용)
CHAPTER_DEFINITIONS = {
    "organization_management": (
        "조직의 비전과 전략을 구성원과 정렬하고, 자원을 효과적으로 배분하여 "
        "조직 전체가 한 방향으로 움직이도록 만드는 역량"
    ),
    "performance_management": (
        "명확한 목표를 설정하고 진척을 관리하며, 객관적인 피드백을 통해 "
        "구성원의 성과 창출을 견인하는 역량"
    ),
    "people_management": (
        "구성원과 신뢰 관계를 구축하고, 동기를 부여하며, "
        "잠재력을 발휘할 수 있도록 코칭하고 육성하는 역량"
    ),
    "work_management": (
        "업무의 우선순위를 정하고 효율적으로 실행하며, "
        "협업과 자원 활용을 최적화하는 역량"
    ),
    "self_management": (
        "자신의 감정과 시간, 학습을 객관적으로 인식하고 관리하여 "
        "지속 가능한 리더십을 발휘하는 역량"
    ),
}

_ACKNOWLEDGMENT_PATTERNS = {
    "short": [
        "네, 그렇게 보실 수 있어요. 큰 틀에서 그게 맞죠.",
        "네, 맞아요. 기본적으로 그 의미가 핵심이죠.",
        "그렇죠. 가장 단순하게 표현하면 그게 맞아요.",
    ],
    "long": [
        "네, 리더님 말씀 잘 들었습니다. 리더님이 보시는 관점도 충분히 이해됩니다.",
        "네, 깊이 있게 보고 계시네요. 리더님 관점 잘 들었습니다.",
        "리더님의 시각이 잘 느껴집니다. 말씀해주신 부분 잘 들었어요.",
    ],
    "default": [
        "네, 리더님 말씀 감사합니다.",
    ],
}


def _select_acknowledgment(user_answer: str | None) -> str:
    """사용자 답변 길이에 따라 호응 패턴 선택."""
    if not user_answer or len(user_answer.strip()) == 0:
        return _ACKNOWLEDGMENT_PATTERNS["default"][0]
    length = len(user_answer.strip())
    if length <= 15:
        return random.choice(_ACKNOWLEDGMENT_PATTERNS["short"])
    return random.choice(_ACKNOWLEDGMENT_PATTERNS["long"])


# (2026-10-19) 라포 2·3턴의 질문은 백엔드 고정 문장. LLM 은 직전 발화 되받기 한 문장만 쓴다.
#   역할 질문에 '오늘' 금지 — 담당 업무는 오늘 일과와 다르다.
RAPPORT_ROLE_QUESTION = "평소 어떤 일을 맡고 계신지 간단히 들려주시겠어요? 팀 규모나 주로 하시는 업무 정도면 됩니다."
RAPPORT_EXPECTATION_QUESTION = "이번 진단에서 기대하시는 것이 있으세요?"
# (2026-10-21) 기대 "없어요"·"아니요": 위로 없이 고정 다리 한 문장 뒤 안내.
RAPPORT_INTRO_BRIDGE_NO_EXPECTATION = "네, 그러면 제가 오늘 흐름부터 설명드릴게요."



def definition_question(chapter_name: str, persona_name: str | None = None, variant: int = 0) -> str:
    """정의 질문 — (2026-11-05 P4-1) 5종 순환. variant 는 챕터 순서 인덱스(0~4) → 한 세션에서 같은 문장이 두 번 나가지 않는다."""
    from diag_project.services.korean import with_josa
    pool = DEFINITION_VARIANTS.get(persona_key(persona_name)) or DEFINITION_VARIANTS["Ella"]
    return pool[int(variant) % len(pool)].format(cn_eul=with_josa(chapter_name, '을/를', quote=True), cn_eun=with_josa(chapter_name, '은/는', quote=True),
                                                 cn_iga=with_josa(chapter_name, '이/가', quote=True), cn=f"'{chapter_name}'")


def definition_question_variants(chapter_name: str, persona_name: str | None = None) -> list[str]:
    """이 코치의 정의 질문 5종 전부(8-k 가 '이미 들어 있는가' 를 볼 때 쓴다)."""
    return [definition_question(chapter_name, persona_name, i) for i in range(len(DEFINITION_VARIANTS["Ella"]))]


# (2026-11-11 P10-2) 정의 질문 5종 — 완결 문장. '~풀면요?'·'~하면요?'·'뭐가 먼저 떠올라요?' 같은 생략형은 폐기(11/11 운영 Olivia 검토).
#   문형: ①어떤 일이라고 생각 ②무엇을 하는 일 ③리더님 말로 설명 ④팀에서 잘 된다는 것은 어떤 모습 ⑤리더님께 어떤 의미.
#   {cn_eul}="'X'를" {cn_eun}="'X'는" {cn_iga}="'X'가" {cn}="'X'". 어미·호칭은 페르소나.
DEFINITION_VARIANTS: dict[str, list[str]] = {
    "Ella": ["{cn_eul} 리더님은 어떤 일이라고 생각하세요?", "리더님이 보시기에 {cn_eun} 무엇을 하는 일인가요?",
             "{cn_eul} 리더님 말로 설명하신다면 어떻게 말씀하시겠어요?", "리더님 팀에서 {cn_iga} 잘 된다는 것은 어떤 모습이라고 생각하세요?",
             "리더님께 {cn_eun} 어떤 의미인가요?"],
    "Jessica": ["{cn_eul} 리더님은 어떤 일이라고 생각하십니까?", "리더님이 보시기에 {cn_eun} 무엇을 하는 일입니까?",
                "{cn_eul} 리더님 말로 설명하신다면 어떻게 말씀하시겠습니까?", "리더님 팀에서 {cn_iga} 잘 된다는 것은 어떤 모습이라고 생각하십니까?",
                "리더님께 {cn_eun} 어떤 의미입니까?"],
    "Olivia": ["{cn_eul} 리더님은 어떤 일이라고 생각하세요?", "리더님이 보기에 {cn_eun} 무엇을 하는 일인가요?",
               "{cn_eul} 리더님 말로 설명한다면 어떻게 말씀하시겠어요?", "리더님 팀에서 {cn_iga} 잘 된다는 건 어떤 모습이라고 생각하세요?",
               "리더님에게 {cn_eun} 어떤 의미예요?"],
    "Daniel": ["{cn_eul} 리더님께서는 어떤 일이라고 생각하십니까?", "리더님께서 보시기에 {cn_eun} 무엇을 하는 일입니까?",
               "{cn_eul} 리더님 말씀으로 설명하신다면 어떻게 말씀하시겠습니까?", "리더님 팀에서 {cn_iga} 잘 된다는 것은 어떤 모습이라고 생각하십니까?",
               "리더님께 {cn_eun} 어떤 의미입니까?"],
    "Michael": ["{cn_eul} 리더님은 어떤 일이라고 생각하세요?", "리더님이 보시기에 {cn_eun} 무엇을 하는 일인가요?",
                "{cn_eul} 리더님 말로 설명하신다면 어떻게 말씀하시겠어요?", "리더님 팀에서 {cn_iga} 잘 된다는 건 어떤 모습이라고 생각하세요?",
                "리더님께 {cn_eun} 어떤 의미인가요?"],
    "Lucas": ["{cn_eul} 리더님은 어떤 일이라고 생각하십니까?", "리더님이 보기에 {cn_eun} 무엇을 하는 일입니까?",
              "{cn_eul} 리더님 말로 설명하면 어떻게 됩니까?", "리더님 팀에서 {cn_iga} 잘 된다는 것은 어떤 모습입니까?",
              "리더님에게 {cn_eun} 어떤 의미입니까?"],
}

# (2026-11-05 P4-1) 정의 질문 앞에 LLM 이 쓰는 '이 영역에서 무엇을 볼지' 1문장의 재료 — LLM 출력에 평서문이 없을 때의 결정론 폴백.
CHAPTER_SCOPE_LINES: dict[str, str] = {
    # (2026-11-06 P7-4 재검토) 역량 정의를 리더 말로 푼 범위 1문장 — LLM 이 안 썼을 때의 폴백
    "organization_management": "팀의 방향을 어떻게 세우고, 바꿔야 할 때 팀을 어떻게 움직이셨는지 함께 짚어볼 거예요.",
    "performance_management": "목표를 어떻게 정하고 점검하셨는지, 결과를 두고 팀원과 어떻게 이야기하셨는지 함께 짚어볼 거예요.",
    "people_management": "팀원 한 사람 한 사람과 신뢰를 어떻게 쌓고, 갈등이나 성장의 순간에 어떻게 대하셨는지 함께 짚어볼 거예요.",
    "work_management": "일을 어떻게 계획하고 시간과 자원을 어떻게 나눠 쓰셨는지 함께 짚어볼 거예요.",
    "self_management": "리더님 자신의 상태를 어떻게 알아차리고, 흔들릴 때 어떻게 중심을 잡으셨는지 함께 짚어볼 거예요.",
}


# (2026-11-14 P12d-1) 합쇼체 코치(Jessica·Daniel·Lucas)용 — 어미표로 바꾸지 않고 사전에 둔다(Lucas 는 말투 교정 대상이 아니라 해요체가 그대로 나갔다)
CHAPTER_SCOPE_LINES_FORMAL: dict[str, str] = {
    "organization_management": "팀의 방향을 어떻게 세우고, 바꿔야 할 때 팀을 어떻게 움직이셨는지 함께 짚어보겠습니다.",
    "performance_management": "목표를 어떻게 정하고 점검하셨는지, 결과를 두고 팀원과 어떻게 이야기하셨는지 함께 짚어보겠습니다.",
    "people_management": "팀원 한 사람 한 사람과 신뢰를 어떻게 쌓고, 갈등이나 성장의 순간에 어떻게 대하셨는지 함께 짚어보겠습니다.",
    "work_management": "일을 어떻게 계획하고 시간과 자원을 어떻게 나눠 쓰셨는지 함께 짚어보겠습니다.",
    "self_management": "리더님 자신의 상태를 어떻게 알아차리고, 흔들릴 때 어떻게 중심을 잡으셨는지 함께 짚어보겠습니다.",
}


def chapter_scope_line(chapter: str | None, persona_name: str | None = None) -> str:
    """영역별 범위 1문장. persona_name 을 주면 그 코치의 말투 판(합쇼체 코치는 합쇼체 문장)."""
    if persona_name is not None and line_register(persona_name) == "formal":
        return CHAPTER_SCOPE_LINES_FORMAL.get(chapter or "", "")
    return CHAPTER_SCOPE_LINES.get(chapter or "", "")


def pause_suggestion_text(elapsed_min: int, persona_name: str | None = None) -> str:
    """(2026-10-22 P1-1) 일시정지 제안 안내 — 질문 없음. 선택은 프론트 버튼('계속 진행하기'/'다음에 하기')이 받는다."""
    _lead = (persona_line(persona_name, "pause_lead", min=int(elapsed_min)) if int(elapsed_min) >= 5
             else persona_line(persona_name, "pause_lead_short"))   # 턴 수 기준 제안(경과 분이 작을 때)은 분을 말하지 않는다
    return f"{_lead} {persona_line(persona_name, 'pause_body')}"


# (2026-10-22) 고정 문장의 페르소나별 변형 — 구조는 하나(어느 자리에 무엇을 붙이는가), 문장은 페르소나. 없는 키·코치는 Ella 로.
PERSONA_LINES: dict[str, dict[str, str]] = {
    "Ella": {
        # (2026-11-11 P10-7) 첫 영역 진입 다리(고정) · (P10-1) 내용 없는 스몰톡 답을 받는 고정 1문장
        "first_bridge": "그럼 첫 영역인 {cn}부터 볼게요.",
        "smalltalk_flat": "그러셨군요.",
        "role_q": "평소 어떤 일을 맡고 계신지 간단히 들려주시겠어요? 팀 규모나 주로 하시는 업무 정도면 됩니다.",
        "expect_q": "이번 진단에서 기대하시는 것이 있으세요?",
        "intro_bridge": "네, 그러면 제가 오늘 흐름부터 설명드릴게요.",
        "definition": "리더님께서는 {cn_eul} 무엇이라고 생각하시나요?",
        "end_bridge": "이제 '{next}'로 이어가 보겠습니다.",
        "close_no_case": "이 영역은 오늘 떠오르는 장면이 많지 않으셨네요. 그것도 그대로 기록할게요.",   # (2026-11-06 P7) 사례 0 챕터 종료 고정 1문장(다리 앞)
        "pause_lead": "리더님, 한 자리에서 {min}분째 이어오고 있습니다.",
        "pause_lead_short": "리더님, 한 자리에서 꽤 길게 이어오고 있습니다.",
        "pause_body": "오늘은 여기서 잠시 쉬어가셔도 괜찮습니다. 이어가실지, 다음에 하실지 아래에서 골라 주세요.",
        # (2026-10-28 P0-1·P0-4) ALIGN 고정 문장·입력 이상 응답
        "align_definition": "저희는 {cn_eul} '{defn}'으로 봐요.",
        "align_guide": "이 {n} 가지가 실제로 어떻게 나타나는지, 있었던 일 몇 가지를 깊게 들어볼게요.",
        "align_open": "먼저 하나부터요.",
        "align_receive_quote": "{quote_rago} 보시는군요.",   # (2026-11-05 → 11-10 P9) ALIGN 되받기 폴백 — 리더 정의의 구절을 그대로 받는다('…라고 보시는군요')
        "reask_anchor": "그럼 여쭤볼게요.",
        "same_input": "앞서 말씀하신 내용과 같네요.",
        "repeat_event": "앞서 들려주신 이야기와 같은 사례로 보여요. 그 사례는 잘 들었으니, 다른 장면 하나를 떠올려 주시면 좋겠어요.",
        "repeat_heard": "그 일은 잘 들었어요.",      # (P12b-3) 닫힌 사례를 다시 말한 답 뒤 — 이 한마디 + 같은 칸의 다른 장면을 묻는 질문
        "question_returned": "질문이 그대로 돌아왔네요. 편하게 답해 주시면 됩니다.",
        "confirm_reask": "시작해도 괜찮으시면 '네'라고 답해 주세요. 궁금한 점이 있으면 먼저 물어보셔도 돼요.",
        "definition_reask": "짧게라도 괜찮아요. {cn_eul} 평소 어떻게 생각하시는지 한 문장만 들려주시겠어요?",
        "continue_ack": "네, 이어갈게요.",
        # (2026-11-12 P11-A2·A3) 되묻기에 붙이는 짧은 사과 · 안내 뒤 거절에 재촉 없이 기다린다는 문장
        "clarify_sorry": "제 질문이 분명하지 않았네요.", "confirm_decline": "알겠어요. 준비되시면 편하실 때 말씀해 주세요. 궁금한 점이 있으면 먼저 물어보셔도 돼요.",
    },
    "Jessica": {
        # (2026-11-11 P10-7) 첫 영역 진입 다리(고정) · (P10-1) 내용 없는 스몰톡 답을 받는 고정 1문장
        "first_bridge": "그럼 첫 영역인 {cn}부터 보겠습니다.",
        "smalltalk_flat": "그러셨군요.",
        "role_q": "평소 어떤 일을 맡고 계신지 간단히 말씀해 주시겠습니까? 팀 규모와 주요 업무 정도면 됩니다.",
        "expect_q": "이번 진단에서 기대하시는 것이 있습니까?",
        "intro_bridge": "알겠습니다. 그러면 오늘 흐름부터 설명드리겠습니다.",
        "definition": "리더님께서는 {cn_eul} 무엇이라고 보십니까?",
        "end_bridge": "이제 '{next}'로 넘어가겠습니다.",
        "close_no_case": "이 영역은 오늘 떠오르는 장면이 많지 않으셨습니다. 그것도 그대로 기록하겠습니다.",   # (2026-11-06 P7) 사례 0 챕터 종료 고정 1문장(다리 앞)
        "pause_lead": "리더님, 한 자리에서 {min}분째입니다.",
        "pause_lead_short": "리더님, 한 자리에서 꽤 길게 이어왔습니다.",
        "pause_body": "오늘은 여기서 잠시 쉬어가셔도 됩니다. 이어갈지, 다음에 할지 아래에서 선택해 주십시오.",
        # (2026-10-28 P0-1·P0-4) ALIGN 고정 문장·입력 이상 응답
        "align_definition": "저희는 {cn_eul} '{defn}'으로 정의합니다.",
        "align_guide": "이 {n} 가지가 실제로 어떻게 나타나는지, 있었던 일 몇 가지를 깊게 듣겠습니다.",
        "align_open": "먼저 하나부터 듣겠습니다.",
        "align_receive_quote": "{quote_rago} 보시는군요.",   # (2026-11-05 → 11-10 P9) ALIGN 되받기 폴백 — 리더 정의의 구절을 그대로 받는다('…라고 보시는군요')
        "reask_anchor": "그러면 여쭙겠습니다.",
        "same_input": "앞서 말씀하신 내용과 같습니다.",
        "repeat_event": "앞서 말씀하신 사례와 같은 건으로 보입니다. 그 건은 확인했으니, 다른 장면 하나를 말씀해 주십시오.",
        "repeat_heard": "그 건은 잘 들었습니다.",      # (P12b-3) 닫힌 사례를 다시 말한 답 뒤 — 이 한마디 + 같은 칸의 다른 장면을 묻는 질문
        "question_returned": "질문이 그대로 돌아왔습니다. 편하게 답해 주시면 됩니다.",
        "confirm_reask": "시작해도 괜찮으시면 '네'라고 답해 주십시오. 궁금한 점이 있으면 먼저 물어보셔도 됩니다.",
        "definition_reask": "짧게라도 괜찮습니다. {cn_eul} 평소 어떻게 보시는지 한 문장만 말씀해 주시겠습니까?",
        "continue_ack": "알겠습니다, 이어가겠습니다.",
        # (2026-11-12 P11-A2·A3) 되묻기에 붙이는 짧은 사과 · 안내 뒤 거절에 재촉 없이 기다린다는 문장
        "clarify_sorry": "제 질문이 분명하지 않았습니다.", "confirm_decline": "알겠습니다. 준비되시면 말씀해 주십시오. 궁금한 점이 있으면 먼저 물어보셔도 됩니다.",
    },
    "Olivia": {
        # (2026-11-11 P10-7) 첫 영역 진입 다리(고정) · (P10-1) 내용 없는 스몰톡 답을 받는 고정 1문장
        "first_bridge": "그럼 첫 영역인 {cn}부터 볼게요.",
        "smalltalk_flat": "그랬군요.",
        "role_q": "평소 어떤 일을 맡고 계세요? 팀 규모나 주로 하시는 업무 정도면 충분해요.",
        "expect_q": "이번 진단에서 기대하는 게 있다면 뭐예요?",
        "intro_bridge": "좋아요, 그럼 오늘 흐름부터 바로 설명드릴게요.",
        "definition": "리더님은 {cn_eul} 뭐라고 생각하세요?",
        "end_bridge": "이제 '{next}' 쪽으로 각도를 바꿔 볼게요.",
        "close_no_case": "이 영역은 오늘 떠오르는 장면이 많지 않으셨네요. 그 모습 그대로 적어 둘게요.",   # (2026-11-06 P7) 사례 0 챕터 종료 고정 1문장(다리 앞)
        "pause_lead": "리더님, 한 자리에서 {min}분째 달려오셨어요.",
        "pause_lead_short": "리더님, 한 자리에서 꽤 길게 달려오셨어요.",
        "pause_body": "오늘은 여기서 잠시 쉬어가도 괜찮아요. 이어갈지, 다음에 할지 아래에서 골라 주세요.",
        # (2026-10-28 P0-1·P0-4) ALIGN 고정 문장·입력 이상 응답
        "align_definition": "저희는 {cn_eul} '{defn}'으로 봐요.",
        "align_guide": "이 {n} 가지가 실제로 어떻게 나타나는지, 있었던 일 몇 가지를 천천히 깊게 들어보려고 해요.",
        "align_open": "먼저 하나부터 볼게요.",
        "align_receive_quote": "{quote_rago} 보고 계시네요.",   # (2026-11-05 → 11-10 P9) ALIGN 되받기 폴백 — 리더 정의의 구절을 그대로 받는다('…라고 보시는군요')
        "reask_anchor": "그럼 바로 물어볼게요.",
        "same_input": "방금 말씀하신 내용과 같은 답이에요.",
        "repeat_event": "앞서 들려주신 장면과 같은 이야기로 보여요. 그건 잘 들었으니, 다른 장면 하나를 꺼내 주시면 좋겠어요.",
        "repeat_heard": "그 이야기는 잘 들었어요.",      # (P12b-3) 닫힌 사례를 다시 말한 답 뒤 — 이 한마디 + 같은 칸의 다른 장면을 묻는 질문
        "question_returned": "질문이 그대로 돌아왔네요. 편하게, 떠오르는 대로 답해 주시면 돼요.",
        "confirm_reask": "시작해도 괜찮으면 '네'라고 답해 주세요. 궁금한 게 있으면 먼저 물어봐도 돼요.",
        "definition_reask": "짧아도 괜찮아요. {cn_eul} 평소 어떻게 생각하는지 한 문장만 들려줄래요?",
        "continue_ack": "좋아요, 이어갈게요.",
        # (2026-11-12 P11-A2·A3) 되묻기에 붙이는 짧은 사과 · 안내 뒤 거절에 재촉 없이 기다린다는 문장
        "clarify_sorry": "제가 어렵게 물었네요.", "confirm_decline": "알겠어요. 준비되면 편할 때 말씀해 주세요. 궁금한 게 있으면 먼저 물어봐도 돼요.",
    },
    "Daniel": {
        # (2026-11-11 P10-7) 첫 영역 진입 다리(고정) · (P10-1) 내용 없는 스몰톡 답을 받는 고정 1문장
        "first_bridge": "그러면 첫 영역인 {cn}부터 여쭙겠습니다.",
        "smalltalk_flat": "그러셨군요.",
        "role_q": "평소 어떤 일을 맡고 계신지 간단히 들려주시겠습니까? 팀 규모나 주로 하시는 업무 정도면 됩니다.",
        "expect_q": "이번 진단에서 기대하시는 바가 있으십니까?",
        "intro_bridge": "네, 그러면 오늘 흐름부터 안내드리겠습니다.",
        "definition": "리더님께서는 {cn_eul} 무엇이라고 생각하십니까?",
        "end_bridge": "이제 '{next}'로 이어가겠습니다.",
        "close_no_case": "이 영역은 오늘 떠오르는 장면이 많지 않으셨습니다. 그 점도 그대로 기록해 두겠습니다.",   # (2026-11-06 P7) 사례 0 챕터 종료 고정 1문장(다리 앞)
        "pause_lead": "리더님, 한 자리에서 {min}분째 이어오고 계십니다.",
        "pause_lead_short": "리더님, 한 자리에서 꽤 길게 이어오고 계십니다.",
        "pause_body": "오늘은 여기서 잠시 쉬어가셔도 괜찮습니다. 이어가실지, 다음에 하실지 아래에서 골라 주십시오.",
        # (2026-10-28 P0-1·P0-4) ALIGN 고정 문장·입력 이상 응답
        "align_definition": "저희는 {cn_eul} '{defn}'으로 보고 있습니다.",
        "align_guide": "이 {n} 가지가 실제로 어떻게 나타나는지, 있었던 일 몇 가지를 깊게 들어보겠습니다.",
        "align_open": "먼저 하나부터 여쭙겠습니다.",
        "align_receive_quote": "{quote_rago} 보시는군요.",   # (2026-11-05 → 11-10 P9) ALIGN 되받기 폴백 — 리더 정의의 구절을 그대로 받는다('…라고 보시는군요')
        "reask_anchor": "그러면 여쭤보겠습니다.",
        "same_input": "앞서 말씀하신 내용과 같습니다.",
        "repeat_event": "앞서 들려주신 이야기와 같은 사례로 보입니다. 그 사례는 잘 들었으니, 다른 장면 하나를 떠올려 주시겠습니까.",
        "repeat_heard": "그 일은 잘 들었습니다.",      # (P12b-3) 닫힌 사례를 다시 말한 답 뒤 — 이 한마디 + 같은 칸의 다른 장면을 묻는 질문
        "question_returned": "질문이 그대로 돌아왔습니다. 편하게 답해 주시면 됩니다.",
        "confirm_reask": "시작해도 괜찮으시면 '네'라고 답해 주십시오. 궁금한 점이 있으면 먼저 물어보셔도 됩니다.",
        "definition_reask": "짧게라도 괜찮습니다. {cn_eul} 평소 어떻게 생각하시는지 한 문장만 들려주시겠습니까?",
        "continue_ack": "네, 이어가겠습니다.",
        # (2026-11-12 P11-A2·A3) 되묻기에 붙이는 짧은 사과 · 안내 뒤 거절에 재촉 없이 기다린다는 문장
        "clarify_sorry": "제 질문이 분명하지 않았습니다.", "confirm_decline": "알겠습니다. 준비되시면 말씀해 주십시오. 궁금한 점이 있으면 먼저 물어보셔도 됩니다.",
    },
    "Michael": {
        # (2026-11-11 P10-7) 첫 영역 진입 다리(고정) · (P10-1) 내용 없는 스몰톡 답을 받는 고정 1문장
        "first_bridge": "그럼 첫 영역인 {cn}부터 바로 가 볼게요.",
        "smalltalk_flat": "그러셨군요.",
        "role_q": "평소 어떤 일을 맡고 계신지 간단히 들려주시겠어요? 팀 규모나 주로 하시는 업무 정도면 됩니다.",
        "expect_q": "이번 진단에서 기대하시는 게 있으세요?",
        "intro_bridge": "그러면 오늘 흐름부터 바로 설명드릴게요.",
        "definition": "리더님께서는 {cn_eul} 뭐라고 생각하세요?",
        "end_bridge": "이제 '{next}'로 바로 가 보겠습니다.",
        "close_no_case": "이 영역은 오늘 떠오르는 장면이 많지 않으셨네요. 그대로 기록하겠습니다.",   # (2026-11-06 P7) 사례 0 챕터 종료 고정 1문장(다리 앞)
        "pause_lead": "리더님, 한 자리에서 {min}분째 달려오셨습니다.",
        "pause_lead_short": "리더님, 한 자리에서 꽤 길게 달려오셨습니다.",
        "pause_body": "오늘은 여기서 잠시 쉬어가셔도 좋습니다. 이어가실지, 다음에 하실지 아래에서 골라 주세요.",
        # (2026-10-28 P0-1·P0-4) ALIGN 고정 문장·입력 이상 응답
        "align_definition": "저희는 {cn_eul} '{defn}'으로 봐요.",
        "align_guide": "이 {n} 가지가 실제로 어떻게 나타나는지, 있었던 일 몇 가지를 제대로 깊게 들어볼게요.",
        "align_open": "먼저 하나부터 가 볼게요.",
        "align_receive_quote": "{quote_rago} 보시는 거네요.",   # (2026-11-05 → 11-10 P9) ALIGN 되받기 폴백 — 리더 정의의 구절을 그대로 받는다('…라고 보시는군요')
        "reask_anchor": "그럼 바로 여쭤볼게요.",
        "same_input": "앞서 말씀하신 내용과 같네요.",
        "repeat_event": "앞서 들려주신 이야기와 같은 사례로 보여요. 그건 잘 들었으니, 다른 장면 하나를 떠올려 주시면 됩니다.",
        "repeat_heard": "그 일은 잘 들었어요.",      # (P12b-3) 닫힌 사례를 다시 말한 답 뒤 — 이 한마디 + 같은 칸의 다른 장면을 묻는 질문
        "question_returned": "질문이 그대로 돌아왔네요. 편하게 답해 주시면 됩니다.",
        "confirm_reask": "시작해도 괜찮으시면 '네'라고 답해 주세요. 궁금한 점이 있으면 먼저 물어보셔도 돼요.",
        "definition_reask": "짧게라도 괜찮아요. {cn_eul} 평소 어떻게 생각하시는지 한 문장만 들려주시겠어요?",
        "continue_ack": "네, 바로 이어갈게요.",
        # (2026-11-12 P11-A2·A3) 되묻기에 붙이는 짧은 사과 · 안내 뒤 거절에 재촉 없이 기다린다는 문장
        "clarify_sorry": "제 질문이 헷갈렸네요.", "confirm_decline": "알겠어요. 준비되시면 말씀해 주세요. 궁금한 점이 있으면 먼저 물어보셔도 돼요.",
    },
    "Lucas": {
        # (2026-11-11 P10-7) 첫 영역 진입 다리(고정) · (P10-1) 내용 없는 스몰톡 답을 받는 고정 1문장
        "first_bridge": "첫 영역, {cn}부터 갑니다.",
        "smalltalk_flat": "그렇군요.",
        "role_q": "평소 맡고 계신 일은요? 팀 규모와 주요 업무 정도면 됩니다.",
        "expect_q": "이번 진단에서 기대하시는 건요?",
        "intro_bridge": "알겠습니다. 오늘 흐름부터 짚겠습니다.",
        "definition": "리더님께서는 {cn_eul} 무엇이라고 정의하십니까?",
        "end_bridge": "이제 '{next}'입니다.",
        "close_no_case": "이 영역은 오늘 떠오르는 장면이 많지 않으셨습니다. 그대로 기록합니다.",   # (2026-11-06 P7) 사례 0 챕터 종료 고정 1문장(다리 앞)
        "pause_lead": "리더님, 한 자리에서 {min}분째입니다.",
        "pause_lead_short": "리더님, 한 자리에서 꽤 길어졌습니다.",
        "pause_body": "오늘은 여기서 쉬어가셔도 됩니다. 이어갈지, 다음에 할지 아래에서 고르십시오.",
        # (2026-10-28 P0-1·P0-4) ALIGN 고정 문장·입력 이상 응답
        "align_definition": "저희 정의는 {cn_eul} '{defn}'입니다.",
        "align_guide": "이 {n} 가지가 실제로 어떻게 드러나는지, 있었던 일 몇 가지를 깊게 묻겠습니다.",
        "align_open": "먼저 하나부터.",
        "align_receive_quote": "{quote_rago} 보시는군요.",   # (2026-11-05 → 11-10 P9) ALIGN 되받기 폴백 — 리더 정의의 구절을 그대로 받는다('…라고 보시는군요')
        "reask_anchor": "그럼 묻겠습니다.",
        "same_input": "앞서 말씀하신 내용과 같습니다.",
        "repeat_event": "앞서 말씀하신 사례와 같은 건입니다. 그 건은 확인했으니 다른 장면 하나만요.",
        "repeat_heard": "그 건은 들었습니다.",      # (P12b-3) 닫힌 사례를 다시 말한 답 뒤 — 이 한마디 + 같은 칸의 다른 장면을 묻는 질문
        "question_returned": "질문이 그대로 돌아왔습니다. 편하게 답해 주시면 됩니다.",
        "confirm_reask": "시작해도 되면 '네'라고 답해 주십시오. 궁금한 점은 먼저 물어보셔도 됩니다.",
        "definition_reask": "짧아도 됩니다. {cn_eul} 평소 어떻게 보시는지 한 문장만요?",
        "continue_ack": "네, 이어갑니다.",
        # (2026-11-12 P11-A2·A3) 되묻기에 붙이는 짧은 사과 · 안내 뒤 거절에 재촉 없이 기다린다는 문장
        "clarify_sorry": "질문이 분명하지 않았습니다.", "confirm_decline": "알겠습니다. 준비되면 말씀해 주십시오. 궁금한 점은 먼저 물어보셔도 됩니다.",
    },
}
# 하위호환 상수(Ella 기본값) — 테스트·도구가 참조
RAPPORT_ROLE_QUESTION = PERSONA_LINES["Ella"]["role_q"]
RAPPORT_EXPECTATION_QUESTION = PERSONA_LINES["Ella"]["expect_q"]
RAPPORT_INTRO_BRIDGE_NO_EXPECTATION = PERSONA_LINES["Ella"]["intro_bridge"]
# (2026-11-11 P10-1) 스몰톡 고정 질문('바쁜 쪽·여유 있는 쪽')은 삭제 — 예비 되물음 SMALLTALK_RESERVE(코치별 3종 × 시간대)로 대체


def persona_key(persona_name: str | None) -> str:
    key = (persona_name or "").split(" ")[0]
    return key if key in PERSONA_LINES else "Ella"


def persona_line(persona_name: str | None, key: str, **fmt) -> str:
    """페르소나별 고정 문장. fmt 는 {cn_eul}·{next}·{phrase}·{min} 자리."""
    line = PERSONA_LINES[persona_key(persona_name)].get(key) or PERSONA_LINES["Ella"][key]
    return line.format(**fmt) if fmt else line


# (2026-11-11 P10-1) 스몰톡 예비 되물음 — 코치별 3종 × 시간대 묶음(아침·낮·저녁). LLM 되물음이 검사에서 떨어지거나 리더 답에 받을 내용이 없을 때
#   재생성 없이 바로 쓴다. 일·역할·팀을 묻지 않고(다음 턴 담당), 이미 지난 시간대만 말하며, 물음표로 끝난다.
SMALLTALK_RESERVE: dict[str, dict[str, list[str]]] = {
    "Ella": {"morning": ["오늘 아침은 여유 있게 시작하셨어요?", "오늘 아침 공기는 어땠어요?", "아침은 챙겨 드셨어요?"],
             "midday": ["점심은 맛있게 드셨어요?", "오전은 금방 지나갔어요?", "오늘 점심에는 뭘 드셨어요?"],
             "evening": ["오늘 하루는 금방 지나갔어요?", "저녁은 드셨어요?", "오늘 낮에 잠깐이라도 쉬는 틈이 있었어요?"]},
    "Jessica": {"morning": ["오늘 아침은 여유 있게 시작하셨습니까?", "오늘 아침 날씨는 어땠습니까?", "아침 식사는 하셨습니까?"],
                "midday": ["점심 식사는 하셨습니까?", "오전은 금방 지나갔습니까?", "오늘 점심에는 무엇을 드셨습니까?"],
                "evening": ["오늘 하루는 금방 지나갔습니까?", "저녁 식사는 하셨습니까?", "오늘 낮에 잠깐 쉬는 틈이 있었습니까?"]},
    "Olivia": {"morning": ["오늘 아침은 어떤 기분으로 시작했어요?", "아침에 창밖은 어땠어요?", "아침은 챙겨 드셨어요?"],
               "midday": ["점심은 뭘 드셨어요?", "오전은 생각보다 금방 지나갔어요?", "점심 먹고 잠깐 걸을 틈은 있었어요?"],
               "evening": ["오늘 하루는 생각보다 금방 지나갔어요?", "저녁은 드셨어요?", "오늘 낮에 숨 돌린 순간이 있었어요?"]},
    "Daniel": {"morning": ["오늘 아침은 여유 있게 시작하셨습니까?", "오늘 아침 공기는 어떠셨습니까?", "아침 식사는 하셨습니까?"],
               "midday": ["점심 식사는 하셨습니까?", "오전은 금방 지나갔습니까?", "오늘 점심에는 무엇을 드셨습니까?"],
               "evening": ["오늘 하루는 금방 지나갔습니까?", "저녁 식사는 하셨습니까?", "오늘 낮에 잠깐 쉬실 틈이 있으셨습니까?"]},
    "Michael": {"morning": ["오늘 아침은 가볍게 시작하셨어요?", "오늘 아침 컨디션은 어땠어요?", "아침은 든든하게 드셨어요?"],
                "midday": ["점심은 든든하게 드셨어요?", "오전은 금방 지나갔어요?", "오늘 점심에는 뭘 드셨어요?"],
                "evening": ["오늘 하루는 금방 지나갔어요?", "저녁은 드셨어요?", "오늘 낮에 잠깐 숨 돌릴 틈은 있었어요?"]},
    "Lucas": {"morning": ["아침은 드셨습니까?", "오늘 아침 컨디션은 어땠습니까?", "오늘 아침은 여유가 있었습니까?"],
              "midday": ["점심은 드셨습니까?", "오전은 금방 갔습니까?", "점심에는 뭘 드셨습니까?"],
              "evening": ["오늘 하루는 금방 갔습니까?", "저녁은 드셨습니까?", "오늘 낮에 쉬는 틈은 있었습니까?"]},
}
_DAYPART_GROUP = {"오전": "morning", "오전 마무리": "morning", "점심": "midday", "오후": "midday", "저녁": "evening", "늦은 시간": "evening"}


def smalltalk_reserve_question(persona_name: str | None, daypart: str | None, variant: int = 0) -> str:
    """지금 시간대 묶음의 예비 되물음 하나(variant 로 3종을 돌린다)."""
    pool = SMALLTALK_RESERVE[persona_key(persona_name)][_DAYPART_GROUP.get(daypart or "", "evening")]
    return pool[int(variant) % len(pool)]


def smalltalk_flat_receive(persona_name: str | None) -> str:
    return persona_line(persona_name, "smalltalk_flat")


# (2026-11-12 P11-A1) 스몰톡 짧은 답이 두 턴 이어질 때(예비 되물음의 답도 짧다) 같은 고정 받기가 연달아 나가지 않게 둘째 턴은 다른 한마디로 받는다
SMALLTALK_FLAT2: dict[str, str] = {"Ella": "네, 그렇군요.", "Jessica": "알겠습니다.", "Olivia": "그렇군요.", "Daniel": "알겠습니다.",
                                   "Michael": "네, 그렇군요.", "Lucas": "네."}


def smalltalk_flat_receive2(persona_name: str | None) -> str:
    return SMALLTALK_FLAT2[persona_key(persona_name)]


# (2026-11-14 P12d-2) 라포 고정 받기 — 3종을 두고 직전 코치 턴에 쓴 것은 뺀다(p12c: '네, 그렇군요.' 두 턴 연속).
SMALLTALK_FLAT3: dict[str, str] = {"Ella": "네, 알겠어요.", "Jessica": "네, 그렇군요.", "Olivia": "네, 알겠어요.", "Daniel": "네, 그렇군요.",
                                   "Michael": "네, 알겠어요.", "Lucas": "알겠습니다."}
# 담당 업무 답이 낱말 나열일 때('교육팀장. 팀원 넷.') — 풀어 옮기지 않고, 다음 질문(기대)으로 이어지는 짧은 말로 받는다
ROLE_FLAT: dict[str, str] = {"Ella": "맡고 계신 일, 잘 알겠어요.", "Jessica": "맡고 계신 업무, 확인했습니다.", "Olivia": "하시는 일, 잘 알겠어요.",
                             "Daniel": "맡고 계신 일, 잘 알겠습니다.", "Michael": "맡고 계신 일, 잘 알겠어요.", "Lucas": "맡으신 일, 알겠습니다."}


def rapport_fixed_receive(persona_name: str | None, prev_coach_text: str | None, *, start: int = 0) -> str:
    """라포 고정 받기 한마디 — 세 가지 가운데 직전 코치 턴에 나간 것은 빼고 고른다(start = 먼저 볼 순번)."""
    k = persona_key(persona_name)
    pool = [persona_line(persona_name, "smalltalk_flat"), SMALLTALK_FLAT2[k], SMALLTALK_FLAT3[k]]
    prev = re.sub(r"\s+", "", prev_coach_text or "")
    order = [pool[(int(start) + i) % len(pool)] for i in range(len(pool))]
    return next((x for x in order if re.sub(r"\s+", "", x) not in prev), order[0])


def role_fixed_receive(persona_name: str | None) -> str:
    return ROLE_FLAT[persona_key(persona_name)]


# (2026-11-14 P12d-1) ALIGN 고정 받기 — 정의 답을 받는 LLM 문장에 리더 답의 낱말이 없거나 금지 꼴로 지워졌을 때 다시 쓰지 않고 이것으로 받는다.
#   영역 순서로 돌린다(세션에서 같은 문장이 이어지지 않게).
ALIGN_FIXED_RECEIVE: dict[str, list[str]] = {
    "Ella": ["그렇게 보고 계시는군요.", "그런 일로 보고 계시네요.", "리더님은 그렇게 정리하고 계시는군요."],
    "Jessica": ["그렇게 보고 계시군요.", "그런 일로 보고 계시는군요.", "리더님께서는 그렇게 정리하고 계시군요."],
    "Olivia": ["그렇게 보고 계시는군요.", "그런 일로 보고 계시네요.", "리더님은 그렇게 정리하고 계시는군요."],
    "Daniel": ["그렇게 보고 계시군요.", "그런 일로 보고 계시는군요.", "리더님께서는 그렇게 정리하고 계시군요."],
    "Michael": ["그렇게 보고 계시는군요.", "그런 일로 보고 계시네요.", "리더님은 그렇게 정리하고 계시는군요."],
    "Lucas": ["그렇게 보시는군요.", "그런 일로 보시네요.", "그렇게 정리하고 계시네요."],
}


def align_fixed_receive(persona_name: str | None, variant: int = 0) -> str:
    pool = ALIGN_FIXED_RECEIVE[persona_key(persona_name)]
    return pool[int(variant) % len(pool)]


def first_chapter_bridge(chapter_name: str, persona_name: str | None = None) -> str:
    """(P10-7) 첫 영역 진입 다리 — "그럼 첫 영역인 조직관리부터 볼게요."(코치별 고정)."""
    return persona_line(persona_name, "first_bridge", cn=chapter_name)


FINISH_CHOICE_LINE = "남은 항목은 이어서 하시면 채워지고, 지금 마치면 최저 수준으로 기록됩니다. 이어서 할까요, 마칠까요?"   # (2026-11-06 P7-3)


def finish_choice_line(persona_name: str | None = None) -> str:
    """(P7-3) 리더가 그만하겠다고 할 때 코치가 덧붙이는 안내 — 선택 버튼(이어서 하기 / 지금 마치기)은 프론트. (P11-A5) 코치 말투별."""
    if not persona_name:
        return FINISH_CHOICE_LINE
    from diag_project.services.system_lines import system_line
    return system_line("finish_choice", persona_name)


def chapter_end_bridge(next_topic: str, persona_name: str | None = None) -> str:
    """(2026-10-21) 챕터 종료: 들은 것 요약(LLM, 사실만) 뒤에 붙는 고정 다리."""
    return persona_line(persona_name, "end_bridge", next=next_topic)


def close_no_case_line(persona_name: str | None = None) -> str:
    """(2026-11-06 P7) 사례가 하나도 성립하지 않은 챕터의 종료 턴: 다리만 남기지 않고 고정 1문장(페르소나별) + 다리. LLM 문장 없음."""
    return persona_line(persona_name, "close_no_case")


def build_diagnosis_intro_message(user_name: str = "리더님") -> str:
    """[DEPRECATED] 작업 24 이후 build_intro_anchor_section + LLM 호응 사용.

    하이브리드 INTRO 패턴으로 전환됨. 이 함수는 legacy 호환용으로 보존.
    """
    return f"{user_name}, " + build_intro_anchor_section()


# (2026-11-12 P11-A5) 진단 안내 본문은 말투별로 따로 쓴다. 종전에는 해요체·합쇼체가 섞인 공용 문장 하나를 어미표로 고쳐 썼는데,
#   그 교정이 시스템 고정 턴에서 조용히 건너뛰어(턴 핸들러의 지역 import 버그) Daniel 에게 '안내드릴게요·이루어져 있어요·시작해볼까요?' 가 나갔다.
_INTRO_BODY: dict[str, str] = {
    "polite": (
        "그럼 오늘 진단이 어떻게 진행되는지 간단히 안내드릴게요.\n\n"
        "진단은 5개 영역으로 이루어져 있어요 — 조직관리, 성과관리, 사람관리, 일관리, 자기관리.\n\n"
        "영역마다 30분 정도 걸리고, 전체로는 150분 이상을 예상해요. "
        "한 번에 다 하기에는 긴 시간이라, 중간에 저장하고 시간 되실 때 이어서 참여하셔도 괜찮아요.\n\n"
        "이 과정은 평가가 아니라 리더십 경험을 함께 나누는 시간이에요. 정답 걱정 없이 편하게 말씀해 주세요.\n\n"
        "그럼 시작해볼까요?"
    ),
    "formal": (
        "그러면 오늘 진단이 어떻게 진행되는지 간단히 안내드리겠습니다.\n\n"
        "진단은 5개 영역으로 이루어져 있습니다 — 조직관리, 성과관리, 사람관리, 일관리, 자기관리.\n\n"
        "영역마다 30분 정도 걸리고, 전체로는 150분 이상을 예상합니다. "
        "한 번에 다 하기에는 긴 시간이라, 중간에 저장하고 시간 되실 때 이어서 참여하셔도 괜찮습니다.\n\n"
        "이 과정은 평가가 아니라 리더십 경험을 함께 나누는 시간입니다. 정답 걱정 없이 편하게 말씀해 주십시오.\n\n"
        "그러면 시작해도 되겠습니까?"
    ),
}
_FORMAL_COACHES = frozenset({"Jessica", "Daniel", "Lucas"})


def line_register(persona_name: str | None) -> str:
    """고정 문장을 고를 말투 — 합쇼체 코치(Jessica·Daniel·Lucas)는 'formal', 나머지는 'polite'."""
    return "formal" if persona_key(persona_name) in _FORMAL_COACHES else "polite"


def build_intro_anchor_section(persona_name: str | None = None, *, lead: bool = True) -> str:
    """진단 안내 본문 (5개 영역 + 총 시간 150분 + 형식) — 코치 말투별. LLM 이 쓴 받는 문장 뒤에 시스템이 붙인다.
    (2026-11-12 P11b-2) lead=False 면 첫 문장('그러면 오늘 진단이 어떻게 진행되는지 간단히 안내드리겠습니다.')을 뺀다 — 기대 답이 없을 때 앞에 붙는
    코치별 다리('네, 그러면 오늘 흐름부터 안내드리겠습니다.')와 같은 말이 두 번 나갔다(시뮬 p11a). 안내 예고는 한 번만."""
    body = _INTRO_BODY[line_register(persona_name)]
    return body if lead else body.split("\n\n", 1)[1]


# (2026-11-12 P11-I) 같은 답이 다시 왔을 때 — 문구 3종을 돌려 쓰고(first), 세션 2회째부터는 같은 질문을 되풀이하지 않고 다른 장면을 청한다(angle, 질문 포함).
DUPLICATE_LINES: dict[str, dict[str, list[str]]] = {
    "polite": {"first": ["앞서 말씀하신 내용과 같네요.", "같은 답이 한 번 더 왔어요.", "방금 답은 앞의 답과 같아요."],
               "angle": ["같은 답을 한 번 더 주셨어요. 그 일 말고 다른 장면이 있으면 그 이야기를 들려주시겠어요?",
                         "방금 답은 앞서 주신 것과 같아요. 다른 날에 있었던 일이 떠오르면 그쪽을 들려주시겠어요?",
                         "같은 내용이 다시 왔어요. 다른 사람과 있었던 장면이 있으면 그 이야기를 해 주시겠어요?"]},
    "formal": {"first": ["앞서 말씀하신 내용과 같습니다.", "같은 답이 한 번 더 왔습니다.", "방금 답은 앞의 답과 같습니다."],
               "angle": ["같은 답을 한 번 더 주셨습니다. 그 일 말고 다른 장면이 있으면 그 이야기를 들려주시겠습니까?",
                         "방금 답은 앞서 주신 것과 같습니다. 다른 날에 있었던 일이 떠오르면 그쪽을 말씀해 주시겠습니까?",
                         "같은 내용이 다시 왔습니다. 다른 사람과 있었던 장면이 있으면 그 이야기를 해 주시겠습니까?"]},
}


def duplicate_answer_line(persona_name: str | None, nth: int) -> tuple[str, bool]:
    """세션에서 nth 번째(1부터) 같은 답 안내. (문장, 질문이 들어 있는가) — 1회째는 안내만(호출자가 직전 질문을 붙인다), 2회째부터는 각도를 바꾼 요청."""
    pool = DUPLICATE_LINES[line_register(persona_name)]
    n = max(1, int(nth))
    if n == 1:
        return pool["first"][0], False
    return pool["angle"][(n - 2) % len(pool["angle"])], True


def build_align_framework_section(chapter: str) -> str:
    """ALIGN 메시지의 framework 부분만 생성 (호응 제외).

    하이브리드 ALIGN 흐름에서 시스템이 직접 출력하는 부분:
    정의 + 세부역량 목록 + 합의 질문.
    LLM 이 생성하는 호응 부분(paraphrase + 칭찬)은 별도로 앞에 붙음.

    Args:
        chapter: 영문 챕터 키 (예: "organization_management")

    Returns:
        framework 부분 텍스트 (호응 없음)
    """
    framework = COMPETENCY_FRAMEWORK.get(chapter)
    if not framework:
        return "역량 정보를 찾을 수 없습니다."

    name = framework["name"]
    description = framework["description"].rstrip(".")
    indicators = framework["indicators"]
    indicator_names = [ind["name"] for ind in indicators.values()]
    indicator_count = len(indicator_names)
    indicator_list = "\n".join(f"- {n}" for n in indicator_names)

    # Step 6 쿠션어: LLM 호응부('…리더님의 그 철학과 같은 맥락으로,')에서
    # 이어받아 한 호흡으로 묶어줌. 사용자 답변 반영(공감/유연 분기)은 LLM 담당.
    return (
        f"저희 진단에서는 이를 포괄하여 {name}를 '{description}'이라고 "
        f"정의하고 있습니다. 말씀하신 결이 이 맥락에 아주 자연스럽게 "
        f"녹아들죠?\n\n"
        f"이 역량의 하위 역량은 다음 {indicator_count}가지입니다:\n"
        f"{indicator_list}\n\n"
        f"앞으로 이 하위 역량들을 중심으로 리더님의 실제 경험을 "
        f"여쭤보려고 해요. 우리가 함께 진행할 역량에 대한 정의가 "
        f"충분히 이해되셨나요?"
    )


def build_chapter_opening_script(
    chapter: str, first_subcompetency: str
) -> str:
    """CHAPTER_OPENING 하이브리드에서 시스템이 직접 출력하는 세션 오프닝 스크립트.

    LLM 은 BEI 질문만 생성. 이 스크립트는 시스템이 앞에 붙임.

    Args:
        chapter: 영문 챕터 키 (예: "organization_management")
        first_subcompetency: 첫 번째 세부역량 이름 (예: "비전 제시 및 공유")
    """
    framework = COMPETENCY_FRAMEWORK.get(chapter)
    chapter_name = framework["name"] if framework else "이번 영역"

    return (
        f"리더님, 첫 번째 세션 시작해볼게요. 앞으로 약 30분 정도 "
        f"'{chapter_name}' 영역에 대해 이야기 나눌 거예요.\n\n"
        f"편하게 답하시면 되고, 생각이 필요한 질문은 천천히 떠올리셔도 "
        f"돼요. 답변이 애매하면 제가 다시 여쭤볼 수 있고요.\n\n"
        f"시작하기 전에 한 가지 약속드릴게요 — 제가 대화 중에 긍정적 "
        f"피드백이나 상황에 대한 판단을 덜 하는 편이에요. 칭찬보다는 "
        f"경험 자체에 집중하기 위해서예요. 저는 리더님의 경험을 함께 "
        f"보는 파트너로 있겠습니다.\n\n"
        f"그럼 첫 번째 세부 역량인 '{first_subcompetency}'부터 시작하겠습니다."
    )


# Deprecated: 호응 포함 구버전. 하이브리드 전환 후 호출 안 함.
# build_align_framework_section + LLM 호응 방식으로 대체됨.
def build_competency_align_message(
    chapter: str,
    user_answer: str | None = None,
) -> str:
    """역량 정의 합의 메시지 생성 (호응 다양화).

    Args:
        chapter: 챕터 키 (예: "organization_management")
        user_answer: 직전 사용자 답변 (길이에 따라 호응 패턴 선택)

    Returns:
        역량 정의 합의 메시지
    """
    framework = COMPETENCY_FRAMEWORK.get(chapter)
    if not framework:
        return "역량 정보를 찾을 수 없습니다."

    name = framework["name"]
    description = framework["description"].rstrip(".")
    indicators = framework["indicators"]
    indicator_names = [ind["name"] for ind in indicators.values()]
    indicator_count = len(indicator_names)
    indicator_list = "\n".join(f"- {n}" for n in indicator_names)

    acknowledgment = _select_acknowledgment(user_answer)

    return (
        f"{acknowledgment}\n\n"
        f"저희가 정의하는 {name}는 '{description}' 으로 보고 있습니다.\n\n"
        f"이 역량은 {indicator_count}가지 세부 역량으로 구성됩니다:\n"
        f"{indicator_list}\n\n"
        f"이 {indicator_count}가지를 중심으로 이야기 나눠봐도 "
        f"괜찮으시겠어요?"
    )


_ONBOARDING_CHAPTER_ORDER = [
    "organization_management",
    "performance_management",
    "people_management",
    "work_management",
    "self_management",
]


def build_onboarding_launch(user_name: str) -> str:
    """온보딩 3-Step의 마지막 — 이름 수용 + 로드맵 + 첫 영역 첫 질문.

    코치 인사(시스템 첫 메시지)에서 이미 자기소개·진단 취지를 전했으므로
    이 턴에서는 자기소개·안부 반복 금지. 이름을 딱 한 문장으로 수용한 뒤
    바로 5개 영역 로드맵을 안내하고 첫 영역(조직관리)의 첫 질문으로 브릿지.

    LLM 호출 없이 시스템이 직접 출력 → 앵무새(반복) 현상 원천 차단.
    """
    names = [
        COMPETENCY_FRAMEWORK[k]["name"]
        for k in _ONBOARDING_CHAPTER_ORDER
        if k in COMPETENCY_FRAMEWORK
    ]
    roadmap = " · ".join(names) if names else "다섯 가지 리더십 영역"
    first_name = COMPETENCY_FRAMEWORK.get(
        "organization_management", {}
    ).get("name", "조직관리")

    return (
        f"반갑습니다, {user_name} 리더님!\n\n"
        f"그럼 바로 시작해볼게요. 오늘은 {roadmap}, 이렇게 다섯 영역을 "
        f"차례로 함께 살펴볼 텐데요. 평가가 아니라 리더님의 실제 경험을 "
        f"같이 들여다보는 자리이니, 정답 걱정 없이 떠오르는 대로 편하게 "
        f"말씀해 주시면 됩니다. 중간에 저장하고 이어서 하셔도 괜찮아요.\n\n"
        f"첫 영역인 '{first_name}'부터 가볍게 열어볼게요. 리더님께 "
        f"'{first_name}' 하면 가장 먼저 떠오르는 장면이나 생각이 "
        f"있으세요? [START_CHAPTER]"
    )


# (제거됨) build_chapter_thought_question — 전환 예고 뒤에 시스템이 덧붙이던
#   '다음 역량 생각 질문' 풀. "'성과관리'을 챙긴다는 건…" 조사 오류의 출처였고,
#   정의 질문(COMPETENCY_ASK)이 두 번 나가는 순서 어긋남을 만들었다.
#   전환 턴은 예고에서 끝내고, 정의 질문은 다음 턴 COMPETENCY_ASK 가 던진다.


# 브릿지(직전 답변 이어받기) 리드도 챕터 순서로 순환.
_BRIDGE_LEADS = [
    "방금 '{ctx}' 이야기를 들으면서, 리더님이 그런 순간들을 어떻게 "
    "마주해오셨는지가 더 궁금해졌어요.",
    "'{ctx}' 하시던 그 결이 마음에 남네요. 그 이야기에서 한 걸음 더 들어가 볼게요.",
    "조금 전 '{ctx}' 말씀이 계속 맴도네요. 그 흐름을 그대로 이어서 여쭤볼게요.",
    "'{ctx}' 이야기, 잘 들었어요. 자연스럽게 다음 이야기로 이어가 볼게요.",
    "방금 들려주신 '{ctx}' 경험이 인상적이었어요. 이어서 하나 더 여쭤볼게요.",
]

_OPEN_CHAPTER_ORDER = [
    k for k in COMPETENCY_FRAMEWORK.keys() if k != "supplementary"
]


def build_chapter_transition_question(chapter: str) -> str:
    """종결+전환 하이브리드의 '안전장치' — LLM 이 계속/휴식 질문을 빠뜨렸을 때만 사용.

    CHAPTER_READY_TO_END 에서 LLM 은 wrap-up(요약+공감) + '계속/휴식 의사 질문'을
    직접 생성한다(layer3_state 프롬프트). 만약 LLM 이 질문을 누락하면, 요약·공감만
    으로 대화가 어색하게 끝나므로 이 함수의 다변화된 계속/휴식 질문을 시스템이
    덧붙인다. (다음 역량의 '내용 질문'이 아니라 '지금 이어갈지/쉴지' 의사 확인)
    """
    framework = COMPETENCY_FRAMEWORK.get(chapter, {})
    name = framework.get("name", "다음 영역")
    variations = [
        f"한숨 돌리고 다음 '{name}' 진단으로 넘어갈까요, 아니면 잠시 "
        f"쉬었다가 이어갈까요?",
        f"바로 이어서 '{name}' 이야기를 살펴봐도 괜찮으실까요? 잠깐 "
        f"쉬어가고 싶으시면 편하게 말씀해 주세요.",
        f"이대로 '{name}'까지 계속 이어가 볼까요, 아니면 여기서 잠깐 "
        f"숨을 돌리고 갈까요?",
        f"괜찮으시면 다음 '{name}' 영역으로 이어가 볼게요 — 혹시 잠시 "
        f"쉬고 싶으시면 그렇게 하셔도 좋아요.",
    ]
    return random.choice(variations)


# ── (2026-09-29) 전체 진단 마무리(5번째 챕터 종료) — 챕터 전환 문구와 구분. 감사 + 리포트 안내 + 한 줄 여운, 총평·칭찬 없음 ──
FINAL_CLOSINGS = {
    "Daniel": ("긴 시간 동안 다섯 영역의 경험을 차분히 들려주셔서 감사합니다. 오늘 나눈 이야기는 결과 리포트로 정리해 드리겠습니다. "
               "화면의 '진단 완료 및 결과 보기'를 누르시면 확인하실 수 있습니다. 오늘 떠올리신 장면 하나가 다음 결정의 작은 기준이 되기를 바랍니다."),
    "Ella": ("오랜 시간 함께해 주셔서 고마워요. 오늘 들려주신 이야기는 결과 리포트로 정리해 드릴게요. "
             "'진단 완료 및 결과 보기'를 누르시면 바로 보실 수 있어요. 오늘 꺼내 보신 장면들이 한동안 곁에 머물러 주면 좋겠어요."),
    "Jessica": ("긴 시간 감사합니다. 오늘 대화는 결과 리포트로 정리됩니다. '진단 완료 및 결과 보기'에서 확인하세요. "
                "오늘 꺼낸 장면 하나가 다음 선택의 기준이 될 겁니다."),
    "Olivia": ("오랜 시간 마음을 열고 이야기해 주셔서 감사해요. 오늘의 대화는 결과 리포트로 정리해 둘게요. "
               "'진단 완료 및 결과 보기'에서 확인하실 수 있어요. 오늘 다른 각도로 비춰 본 장면들이 조용히 남아 있기를 바라요."),
    "Michael": ("긴 시간 함께 달려 주셔서 감사합니다. 오늘 이야기는 결과 리포트로 정리해 드립니다. "
                "'진단 완료 및 결과 보기'를 누르시면 바로 확인하실 수 있습니다. 오늘 떠올린 장면에서 다음 한 걸음이 나오길 바랍니다."),
    "Lucas": ("긴 시간 감사합니다. 오늘 내용은 결과 리포트로 정리됩니다. '진단 완료 및 결과 보기'에서 확인하시면 됩니다. "
              "오늘 짚은 장면 하나면 충분합니다."),
}
_FINAL_DEFAULT = ("긴 시간 함께해 주셔서 감사합니다. 오늘 나눈 이야기는 결과 리포트로 정리해 드리겠습니다. "
                  "'진단 완료 및 결과 보기'를 누르시면 확인하실 수 있습니다. 오늘 떠올리신 장면들이 다음 걸음에 작은 기준이 되기를 바랍니다.")


# (2026-11-11 P10-2) 페르소나 슬롯 — 고정 문장 금지. 문장은 LLM 이 그 사례의 구체 내용(리더가 고른 선택과 버린 선택)을 넣어 쓴다(services/slot_render.py).
#   여기에는 '코치마다 무엇을 하는가'(종류)와 상한만 둔다. 챕터당 1회·세션 5회, Michael 실행 의지 질문은 세션 3회. Ella 는 슬롯 없음.
#   Jessica 기준 / Lucas 한 줄 이유 / Olivia 버린 선택 가정·상대 자리 / Michael 응원(+다음 턴 실행 의지) / Daniel 선배 관찰.
SLOT_KINDS: dict[str, tuple[str, ...]] = {
    "Jessica": ("criterion",), "Lucas": ("reason",),
    # (2026-11-14 P12e-1) 반사실 질문('그렇게 하지 않으셨다면 …')은 삭제 — 일어나지 않은 일을 가정해 묻지 않는다. Olivia 는 '그 사람 자리' 한 종류만.
    "Olivia": ("other_side",),
    "Michael": ("cheer",), "Daniel": ("observation",),
}
# 슬롯 질문이 겨냥하는 사례 슬롯(이미 찼으면 넣지 않는다). 평서문 종류(응원·관찰)는 겨냥 슬롯 없음.
SLOT_KIND_TARGET: dict[str, str] = {"criterion": "criterion", "reason": "criterion", "counterfactual": "criterion", "other_side": "reaction"}
MICHAEL_WILL_SESSION_CAP = 3
SLOT_SESSION_CAP = 5


def slot_kind_for(persona_name: str | None, n_used: int = 0) -> str | None:
    """이 코치가 이번에 쓸 슬롯 종류 — 세션에서 이미 쓴 횟수로 돌린다(Olivia 만 두 종류). 슬롯 없는 코치는 None."""
    kinds = SLOT_KINDS.get(persona_key(persona_name))
    return kinds[int(n_used) % len(kinds)] if kinds else None


def all_fixed_sentences() -> list[str]:
    """린트·가드가 '고정 문장'으로 제외할 문장 전부 — (P10-2) 슬롯 문장은 더 이상 고정이 아니라 ALIGN 다리만 남는다."""
    out: list[str] = []
    for v in ALIGN_OPEN_VARIANTS.values():
        out.extend(v)                      # '먼저 하나부터.'(Lucas) 같은 서술어 없는 고정 다리는 흉터가 아니다
    for v in ALIGN_FIXED_RECEIVE.values():
        out.extend(v)                      # (P12d-1) ALIGN 고정 받기
    out.extend(list(SMALLTALK_FLAT3.values()) + list(ROLE_FLAT.values()))   # (P12d-2) 라포 고정 받기
    return out


# (2026-11-05 P4-1) ALIGN 고정 안내·다리 — 3종 순환(세션 5챕터에서 같은 문장 ≤2회). {n} = 한/두/…/아홉
ALIGN_GUIDE_VARIANTS: dict[str, list[str]] = {
    "Ella": ["이 {n} 가지가 실제로 어떻게 나타나는지, 있었던 일 몇 가지를 깊게 들어볼게요.", "{n} 가지 모두 실제로 있었던 일로 들어보고 싶어요.",
             "이 {n} 가지가 리더님 팀에서 어떤 장면으로 나왔는지 하나씩 확인해 볼게요."],
    "Jessica": ["이 {n} 가지가 실제로 어떻게 나타나는지, 있었던 일 몇 가지를 깊게 듣겠습니다.", "{n} 가지 모두 실제 있었던 일로 확인하겠습니다.",
                "이 {n} 가지가 리더님 팀에서 어떤 장면으로 나왔는지 하나씩 듣겠습니다."],
    "Olivia": ["이 {n} 가지가 실제로 어떻게 나타나는지, 있었던 일 몇 가지를 천천히 깊게 들어보려고 해요.", "{n} 가지 모두 실제로 있었던 장면으로 들어볼게요.",
               "이 {n} 가지가 리더님 팀에서는 어떤 모습이었는지 하나씩 볼게요."],
    "Daniel": ["이 {n} 가지가 실제로 어떻게 나타나는지, 있었던 일 몇 가지를 깊게 들어보겠습니다.", "{n} 가지 모두 실제로 있었던 일로 여쭙겠습니다.",
               "이 {n} 가지가 리더님 팀에서 어떤 장면으로 나왔는지 하나씩 듣겠습니다."],
    "Michael": ["이 {n} 가지가 실제로 어떻게 나타나는지, 있었던 일 몇 가지를 제대로 깊게 들어볼게요.", "{n} 가지 전부 실제로 있었던 일로 들어볼게요.",
                "이 {n} 가지가 리더님 팀에서 어떤 장면으로 나왔는지 하나씩 가 볼게요."],
    "Lucas": ["이 {n} 가지가 실제로 어떻게 드러나는지, 있었던 일 몇 가지를 깊게 묻겠습니다.", "{n} 가지 전부 실제 있었던 일로 묻겠습니다.",
              "이 {n} 가지가 리더님 팀에서 어떤 장면이었는지 하나씩 묻겠습니다."],
}
ALIGN_OPEN_VARIANTS: dict[str, list[str]] = {
    "Ella": ["먼저 하나부터요.", "하나씩 가 볼게요.", "첫 장면부터 들어볼게요."],
    "Jessica": ["먼저 하나부터 듣겠습니다.", "하나씩 가겠습니다.", "첫 장면부터 듣겠습니다."],
    "Olivia": ["먼저 하나부터 볼게요.", "하나씩 들여다볼게요.", "첫 장면부터 볼게요."],
    "Daniel": ["먼저 하나부터 여쭙겠습니다.", "하나씩 여쭙겠습니다.", "첫 장면부터 듣겠습니다."],
    "Michael": ["먼저 하나부터 가 볼게요.", "하나씩 바로 가 볼게요.", "첫 장면부터 가 볼게요."],
    "Lucas": ["먼저 하나부터.", "하나씩 갑니다.", "첫 장면부터."],
}


def align_guide_line(n_word: str, persona_name: str | None, variant: int = 0) -> str:
    pool = ALIGN_GUIDE_VARIANTS.get(persona_key(persona_name)) or ALIGN_GUIDE_VARIANTS["Ella"]
    return pool[int(variant) % len(pool)].format(n=n_word)


def align_open_line(persona_name: str | None, variant: int = 0) -> str:
    pool = ALIGN_OPEN_VARIANTS.get(persona_key(persona_name)) or ALIGN_OPEN_VARIANTS["Ella"]
    return pool[int(variant) % len(pool)]


def final_closing_message(persona_name: str | None) -> str:
    return FINAL_CLOSINGS.get((persona_name or "").split(" ")[0], _FINAL_DEFAULT)
