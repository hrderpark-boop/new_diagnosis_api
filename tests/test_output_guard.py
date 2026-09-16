"""2026-09-16 Daniel 재주행 검토 5건 — 출력 가드·넓이 하한·전환 대기 회귀(LLM·DB 없음)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services import output_guard as G  # noqa: E402
from diag_project.services import traversal as T  # noqa: E402
from diag_project.services import instruction_decider as ID  # noqa: E402
from diag_project.services.style_tracker import format_style_constraints, is_recap_opening  # noqa: E402

ALIGN_LLM = ("'조직을 효율적으로 관리하는 것'이라고 하셨죠. 그 효율은 방향과 사람, 변화에서 나옵니다.\n\n"
             "· 비전 제시 및 공유\n· 전략적 사고\n\n말씀하신 것과 크게 다르지 않죠? 이제 경험 속으로 들어가 볼까요?")
ANCHOR = "먼저 하나 여쭤볼게요. 새로운 방향에 반신반의하는 팀원들을 설득하셨던 일, 최근에 있으셨어요?"


# ── 1) ALIGN 이중 질문 ──
def test_align_trailing_questions_removed_so_only_anchor_question_remains():
    body, n = G.strip_trailing_question(ALIGN_LLM)
    assert n == 2 and not body.rstrip().endswith("?")
    final = f"{body}\n\n{ANCHOR}"
    assert final.count("?") == 1
    same, n0 = G.strip_trailing_question("정의 제시입니다. 마지막은 평서문입니다.")
    assert n0 == 0 and same.endswith("평서문입니다.")


# ── 2) 전환 환각 + 대기 중 텍스트 ──
def test_transition_claim_detected_and_stripped():
    t = ("네, 잘 들었습니다. 이로써 조직관리 영역에 대한 경험을 충분히 들었습니다. "
         "다음 챕터로 넘어가겠습니다.")
    assert G.has_transition_claim(t)
    out, n = G.strip_transition_sentences("팀원들의 반발이 있었군요. 다음 챕터로 넘어가겠습니다. 그때 무엇을 먼저 하셨습니까?")
    assert n == 1 and "다음 챕터" not in out and out.endswith("하셨습니까?")
    assert "CHAPTER_READY_TO_END" in G.TRANSITION_ALLOWED_INSTRUCTIONS


def _wait_state(text: str) -> dict:
    return {
        "awaiting_next_chapter_choice": True, "last_user_response": text,
        "chapter": "performance_management", "chapter_started": True, "turn_count": 0,
        "rapport_complete": True, "intro_done": True, "rapport_turn_count": 3,
        "definition_asked": False, "competency_aligned": False,
        "events_collected": 0, "events_with_star_70": 0, "has_contrary_probe": False,
        "avoidance_count_in_chapter": 0, "contains_avoidance_keywords": False,
        "all_subcompetencies": ["목표설정 및 공유"], "unexplored_subcompetencies": ["목표설정 및 공유"],
        "asked_in_chapter": [], "current_event_id": None, "current_event_star_coverage": None,
    }


def test_waiting_for_next_chapter_choice_consent_vs_free_text():
    # '네' 계열은 확인으로 → 정의 질문(COMPETENCY_ASK) 경로로 통과(대기 instruction 아님)
    for ok in ("네", "네, 알겠습니다", "좋아요 다음으로", "다음 챕터 진행해요", "계속할게요"):
        ins = ID.decide_instruction(_wait_state(ok))
        assert ins != "AWAIT_NEXT_CHAPTER_CHOICE", (ok, ins)
    # 그 외 텍스트(이전 챕터 답변처럼 보이는 자유 서술) → 안내만, 탐침 재개 없음
    ins = ID.decide_instruction(_wait_state("팀원들과 회의를 통해 자료를 분석하기 시작했죠"))
    assert ins == "AWAIT_NEXT_CHAPTER_CHOICE"
    assert ID.decide_instruction(_wait_state("오늘은 여기서 잠시 쉴게요")) == "USER_REQUESTS_PAUSE"
    assert ID.is_next_chapter_consent("아직 아니요") is False


# ── 3) 앵커 턴 이름 노출 · 오타겟 ──
NAMES = ["비전 제시 및 공유", "전략적 사고", "변화관리(변화지향)", "혁신적 사고", "성과지표 관리(KPI)"]


def test_sub_names_and_paren_variants_detected():
    t = "이제 조직관리 영역에서 '전략적 사고'와 관련하여, 방향성을 제시하신 경험이 있으시다면 들려주시겠습니까?"
    assert "전략적 사고" in G.find_sub_names(t, NAMES)
    assert "변화관리" in G.find_sub_names("변화관리 측면에서 여쭙니다.", NAMES)
    assert "KPI" in G.find_sub_names("KPI를 어떻게 잡으셨나요?", NAMES)
    assert G.find_sub_names("새 방식에 반신반의하는 팀원을 설득하셨던 일이 있으셨어요?", NAMES) == []


def test_off_target_by_noun_overlap():
    asked_q = ["최근에 정보가 충분치 않은 상황에서도 중요한 결정을 내려야 했던 때가 있으셨습니까? 그때 어떤 기준으로 결정하셨는지 궁금합니다."]
    off, q = G.off_target_overlap("정보가 충분치 않은 상황에서 중요한 결정을 내리셨을 때 어떤 기준으로 결정하셨습니까?", asked_q)
    assert off and q == asked_q[0]
    off2, _ = G.off_target_overlap("늘 하던 방식이 답답해서 다른 방법을 시도하신 일이 있으실까요?", asked_q)
    assert not off2
    assert G.template_anchor("질문?").endswith("질문?")


# ── 4-b) 평가적 칭찬 금지 ──
def test_praise_detected_and_stripped_keeping_question():
    t = ("네, 현장의 목소리를 경청하셨다는 말씀, 잘 들었습니다. 초기 혼란을 극복하신 훌륭한 경험이셨습니다. "
         "리더님의 깊은 통찰력이 매우 인상 깊습니다. 그때 무엇을 먼저 하셨습니까?")
    found = G.find_praise(t)
    assert "훌륭한" in found and any("인상 깊" in f for f in found) and any("통찰" in f for f in found)
    out, n = G.strip_praise(t)
    assert n == 2 and "훌륭한" not in out and "통찰" not in out and out.endswith("하셨습니까?")
    for p in ("참으로 의미 있는 성과", "깊이 다가옵니다", "본질을 정확히 짚어주셨습니다"):
        assert G.find_praise(p), p
    assert G.find_praise("그 결정을 내리셨군요. 쉽지 않은 자리였겠습니다.") == []   # 사실 확인·상황 인정은 허용
    # 전부 칭찬이면 질문 문장에서 구절만 걷어낸다
    out2, _ = G.strip_praise("훌륭한 결정이셨는데, 그다음은 어떻게 하셨습니까?")
    assert "훌륭한" not in out2 and out2.endswith("하셨습니까?")


def test_praise_ban_and_lead_rule_in_style_block_for_every_persona():
    for n in ("Ella (엘라)", "Jessica (제시카)", "Olivia (올리비아)", "Daniel (다니엘)", "Michael (마이클)", "Lucas (루카스)"):
        t = format_style_constraints({}, n, "CONTINUE_NORMAL")
        assert "평가적 칭찬 금지" in t and "한 문장" in t, n
    # 프로필에서 칭찬 예시 제거(코치 소개문의 '공감 능력이 뛰어난' 같은 자기 묘사는 대상 아님)
    from diag_project.data.coaches_persona import COACHES_PERSONA
    prompts = " ".join(v["system_prompt"] for v in COACHES_PERSONA.values())
    for gone in ("꽤 과감했네요", "본질을 정확히 짚", "잘 버티셨습니다", "해야 할 몫"):
        assert gone not in prompts, gone
    assert sum(1 for v in COACHES_PERSONA.values() if "칭찬" in v["system_prompt"]) == 6   # 6명 전원 금지 명시


# ── 4-a/4-c) 되받기 판정 확장 + 리드 한 줄 ──
def test_recap_markers_extended_and_lead_trimmed():
    assert is_recap_opening("네, 현장의 목소리를 경청하셨다는 말씀, 잘 들었습니다.")
    assert is_recap_opening("네, 새로운 협업 툴 도입 시 반발이 있었다는 말씀, 잘 알겠습니다.")
    user = "현장의 피드백을 반영해 툴의 단계를 간소화했습니다."
    t = ("네, 현장의 목소리를 경청하셨다는 말씀, 잘 들었습니다. 쉽지 않은 자리였겠습니다. "
         "그때 무엇을 먼저 하셨습니까?")
    out, n = G.trim_lead_sentences(t, forbid_recap=True, user_text=user, forbid_ne=True)
    assert out == "쉽지 않은 자리였겠습니다. 그때 무엇을 먼저 하셨습니까?" and n == 1
    # 허용 턴: 리드 2문장 → 마지막 한 줄만
    out2, n2 = G.trim_lead_sentences("피드백을 반영하셨군요. 쉽지 않은 자리였겠습니다. 그다음은요?", False, user)
    assert out2 == "쉽지 않은 자리였겠습니다. 그다음은요?" and n2 == 1
    # 질문 없는 출력은 그대로
    same, n3 = G.trim_lead_sentences("이 영역, 여기서 잘 매듭짓겠습니다.", True, user)
    assert n3 == 0 and same.startswith("이 영역")


# ── 5) 넓이 하한 ──
def test_breadth_floor_all_when_four_or_fewer():
    assert T.min_explored_for(4) == 4 and T.min_explored_for(3) == 3
    assert T.min_explored_for(5) == 3 and T.min_explored_for(9) == 6
    assert ID.MIN_EXPLORED == {"organization_management": 4, "performance_management": 3,
                               "people_management": 6, "work_management": 3, "self_management": 3}
    assert T.chapter_turn_cap(ID.MIN_EXPLORED["organization_management"]) == 16
    for ch, m in ID.MIN_EXPLORED.items():
        assert T.chapter_turn_cap(m) < ID.MAX_TURNS[ch]
