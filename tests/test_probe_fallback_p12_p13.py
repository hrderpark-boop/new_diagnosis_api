"""(2026-10-22 P1-2·P1-3) Result 폴백·정도 부사 수치 질문 / 질문 없는 턴 금지·간접 질문·챕터 종료 다리 중복·'네' 단답 (LLM·DB 없음)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services import output_guard as G  # noqa: E402
from diag_project.services.intro_messages import RAPPORT_SMALLTALK_FALLBACK_QUESTION, definition_question  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── P1-2 ──
def test_result_fallback_no_quoted_noun_and_alternates():
    a = G.result_fallback_question("두 달 걸려서 새 체계로 갔습니다", None, alt=0)
    b = G.result_fallback_question("두 달 걸려서 새 체계로 갔습니다", None, alt=1)
    assert a == "그래서 그 뒤에는 어떻게 됐어요?" and b == "결과는 어떻게 나왔어요?"
    assert "'" not in a and "이후로는" not in a


def test_degree_adverb_without_number_triggers_quantify():
    assert G.needs_quantify_probe("불필요한 회의 시간이 획기적으로 줄고 팀 생산성이 대폭 향상되었습니다.")
    assert not G.needs_quantify_probe("회의 시간이 30% 줄었습니다.")          # 숫자 있음
    assert not G.needs_quantify_probe("회의 시간이 줄었습니다.")              # 정도 부사 없음
    assert G.result_fallback_question("회의 시간이 훨씬 줄었어요", None, alt=0) == G.RESULT_QUANTIFY_QUESTION   # (P2-0) 수식 대상이 시간
    assert G.is_quantify_question("어느 정도였어요?") and G.is_quantify_question("몇 명이나 참여했나요?")
    assert not G.is_quantify_question("그 뒤로 어떻게 됐어요?")


# ── P1-3 ──
def test_indirect_questions_count_as_questions():
    for s in ("그 과정에서 리더님이 가장 신경 쓰셨던 지점이 무엇이었는지 이어서 여쭙고 싶었어요.", "그때 어떤 마음이었는지 궁금해요.",
              "그 장면을 조금 더 들려주세요.", "그때 상황을 떠올려 주세요.", "기준이 무엇이었는지 말씀해 주세요."):
        assert G.is_question(s) or "여쭙고" in s, s
    assert G.is_question("그때 어떤 마음이었는지 궁금해요.") and G.is_question("그 장면을 조금 더 들려주세요.")
    assert not G.is_question("팀원들과 따로 만나 이유를 설명하셨군요.")
    # 전환·종료 턴: 간접 질문도 제거 / 탐침 턴: 한 턴 한 질문에 포함
    assert G.drop_question_sentences("설명하셨군요. 그때 마음이 궁금해요.")[0] == "설명하셨군요."
    assert G.keep_last_question("그때 마음이 궁금해요. 결과는 어땠나요?") == ("결과는 어땠나요?", 1)


def test_chapter_end_bridge_not_duplicated():
    out, n = G.strip_transition_sentences("개편 때 1:1 면담으로 설명하셨습니다. 이제 '성과관리'로 이어가 보겠습니다.")
    assert n == 1 and "이어가 보겠습니다" not in out


def test_fixed_questions_for_questionless_turns():
    assert RAPPORT_SMALLTALK_FALLBACK_QUESTION.endswith("?")
    assert definition_question("조직관리") == "리더님께서는 '조직관리'를 무엇이라고 생각하시나요?"
    assert definition_question("성과관리") == "리더님께서는 '성과관리'를 무엇이라고 생각하시나요?"


def test_route_wiring():
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert "_pl_r('smalltalk_q')" in src and '_tm["no_q_fix"] = "smalltalk"' in src
    assert "_fixed_q if _consent_in else" in src                       # '네' 단답 → 되받기 생략
    assert "# 8-k." in src and "definition_question(_cn_k, " in src   # 페르소나 인자
    assert 'state["result_quantify"]' in src and '"quantify")]).strip()' in src   # 수치 질문은 persona_line
    assert "_sts_e(_sum)" in src                                        # 챕터 종료 요약에서 전환 문장 제거
    for alt in (0, 1, 2):
        q = G.result_fallback_question("팀원과 따로 만나 이유를 설명했죠", "앞 발화", alt=alt)
        assert "이후로는" not in q and "'" not in q                       # 명사 따옴표 폴백 폐지
