"""(2026-10-21) 조직관리 대화 기준 구조 수정 — 라포 4단계·앵커 접착·탐침 품질·앵커 렌더링 플래그 (LLM·DB 없음)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.data.competencies import SUBCOMPETENCY_ANCHOR_QUESTIONS, SUBCOMPETENCY_MUST_ASK  # noqa: E402
from diag_project.prompts.phase3a import layer3_state as L  # noqa: E402
from diag_project.services import anchor_render as AR  # noqa: E402
from diag_project.services import output_guard as G  # noqa: E402
from diag_project.services.intro_messages import RAPPORT_INTRO_BRIDGE_NO_EXPECTATION, chapter_end_bridge  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASE = {"chapter": "organization_management", "turn_count": 4, "events_collected": 1, "events_with_star_70": 1,
         "current_event_id": None, "current_event_star_coverage": None, "has_contrary_probe": False,
         "avoidance_count_in_chapter": 0, "all_subcompetencies": ["비전 제시 및 공유", "전략적 사고", "변화관리(변화지향)", "혁신적 사고"],
         "explored_subcompetencies": ["비전 제시 및 공유"], "unexplored_subcompetencies": ["전략적 사고", "변화관리(변화지향)", "혁신적 사고"],
         "asked_in_chapter": ["비전 제시 및 공유", "전략적 사고"], "current_target_sub": "전략적 사고",
         "coach_persona": {"name": "Ella"}, "first_subcompetency_name": "비전 제시 및 공유",
         "participant_context": {"role_summary": "교육팀장, 5명"}}


def _g(instr, **over):
    return L._get_instruction_guide(instr, dict(_BASE, instruction_for_this_turn=instr, **over))


# ── A. 라포 ──
def test_smalltalk_guide_allows_one_followup_from_leader_words():
    g = L._get_instruction_guide("RAPPORT_BUILDING", {"instruction_for_this_turn": "RAPPORT_BUILDING", "forced_rapport_category": "스몰톡",
                                                       "current_hour_text": "오후 4시", "current_time_tone": "활기찬 오후", "last_user_response": "요즘 바빠요"})
    assert "스몰톡 받기" in g and "되물음 1개" in g and "리더님 발화에서 나온 것만" in g
    assert "담당 업무·기대 질문은 다음 턴" in g
    assert "요즘 바빠요" not in g.split("리더님이 방금")[0]      # 입력과 겹치는 예시 없음(금지·허용 예 모두)
    assert "그럭저럭" not in g


def test_expectation_turn_reacts_to_role():
    g = L._get_instruction_guide("RAPPORT_BUILDING", {"instruction_for_this_turn": "RAPPORT_BUILDING", "forced_rapport_category": "기대",
                                                       "current_hour_text": "오후 4시", "current_time_tone": "활기찬 오후", "last_user_response": "교육팀장이고 5명이에요"})
    assert "역할에 대한 반응 한 문장" in g and "하나를 집어서" in g


def test_receive_sentences_and_fixed_bridge():
    assert G.receive_sentences("바쁘신 쪽이군요. 그래도 잘 버티고 계시네요. 요즘은 어느 쪽이 더 바쁘세요?") == \
        "바쁘신 쪽이군요. 그래도 잘 버티고 계시네요. 요즘은 어느 쪽이 더 바쁘세요?"
    assert G.receive_sentences("첫째. 둘째. 셋째. 질문1? 질문2?") == "첫째. 둘째. 질문2?"
    assert G.receive_sentences("질문만?", allow_question=False) == "그러셨군요."
    assert "괜찮" not in RAPPORT_INTRO_BRIDGE_NO_EXPECTATION and RAPPORT_INTRO_BRIDGE_NO_EXPECTATION.startswith("네, 그러면")


def test_echo_guard_4chars_but_quote_handles_allowed():
    u = "그럭저럭 지내고 있어요"
    assert G.echoes_user("그럭저럭 지내고 계시는군요.", u)
    assert not G.echoes_user("'그럭저럭'이라 하시니, 바쁜 쪽이세요 아니면 지루한 쪽이세요?", u)
    assert not G.echoes_user("그럭저럭이라는 말씀이 편하게 들리네요.", u)
    assert not G.echoes_user("괜찮다고 하시니 다행이네요.", u)


# ── B. 앵커 접착 ──
def test_align_guide_forbids_questions_and_foreign_quotes():
    g = _g("COMPETENCY_ALIGN", last_user_response="조직을 효율적으로 관리하는 거요")
    assert "질문 금지" in g and "인용 규칙" in g and "description 의 말" in g


def test_foreign_quote_guard():
    user = "조직을 효율적으로 관리하는 거요"
    out = "'효율적으로 관리'한다고 하셨는데, 그 '효과적'이 어디서 나오는지 저희는 이렇게 봐요. '조직관리'는 네 가지입니다."
    bad = G.foreign_quotes(out, user, exempt=["조직관리", "비전 제시 및 공유"])
    assert bad == ["효과적"]
    assert G.strip_quote_marks(out, bad).count("'효과적'") == 0 and "'효율적으로 관리'" in G.strip_quote_marks(out, bad)
    # 어미 차이는 리더 말로 인정(리플레이: '…내야 한다' vs 발화 '…내야 하니까요', '…하는 것' vs '…하는 거요')
    user2 = "조직을 효율적으로 관리하는 거요. 한정된 자원으로 결과를 내야 하니까요"
    assert G.foreign_quotes("'한정된 자원으로 결과를 내야 한다'는 말씀과 '조직을 효율적으로 관리하는 것'이라는 관점", user2) == []
    assert G.foreign_quotes("'조직의 방향을 세우고 구성원의 참여를 이끌어내는 능력'으로 봅니다", user2) == ["조직의 방향을 세우고 구성원의 참여를 이끌어내는 능력"]


def test_transition_guide_two_sentences_no_question_anchor_by_system():
    g = _g("STAR_COMPLETE_NEW_EVENT")
    assert "질문은 쓰지 않습니다" in g and "되받기(1문장, 필수)" in g and "다리(1문장, 필수)" in g
    assert "단독 출력 금지" in g and "시스템이 붙일 앵커" in g
    assert "새로운 사례를 들려주셨네요" in g       # 금지 목록에 명시
    assert G.is_transition_only("이번엔 조금 다른 장면입니다.")
    assert not G.is_transition_only("반발한 팀원을 따로 만나 이유부터 설명하신 거군요. 이번엔 조금 다른 장면입니다.")


def test_state_leak_guard():
    assert G.find_state_leak("새로운 사례를 들려주셨네요. 그때 어떻게 하셨어요?") == ["새로운 사례를 들려주"]
    assert G.strip_state_leak("새로운 사례를 들려주셨네요. 그때 어떻게 하셨어요?") == ("그때 어떻게 하셨어요?", 1)
    assert G.find_state_leak("이 영역은 여기까지 충분히 들었습니다.") and not G.find_state_leak("팀원과 따로 만나 이유를 설명하셨군요.")


def test_chapter_end_summary_contract():
    g = _g("CHAPTER_READY_TO_END", no_yield_forced=False)
    assert "들은 것 요약(2문장, 사실만)" in g and "시스템이 붙입니다" in g
    assert chapter_end_bridge("성과관리") == "이제 '성과관리'로 이어가 보겠습니다."
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    code_only = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "여기까지 충분히 들었습니다" not in code_only          # 주석 제외, 출력 경로에는 없다
    assert "wrap_up = f\"{_sum} {chapter_end_bridge(chapter_to_topic(_next_ch))}\"" in src


# ── C. 탐침 품질 ──
def test_one_question_and_moment_form():
    assert G.keep_last_question("그때 어떻게 하셨어요? 팀원들은요? 결과는 어땠을까요?") == ("결과는 어땠을까요?", 2)
    assert G.keep_last_question("그러셨군요. 그때 어떻게 하셨어요?") == ("그러셨군요. 그때 어떻게 하셨어요?", 0)
    assert G.fix_moment_question("팀원이 흔들린다고 알아채신 순간이 있었을까요?") == ("팀원이 흔들린다고 알아채신 장면은 언제였을까요?", 1)
    assert G.fix_moment_question("그 결정은 언제였을까요?")[1] == 0
    assert G.fix_moment_question("외부 강사를 다시 찾자는 이야기가 나왔던 순간도 있었을까요?")[0].endswith("나왔던 장면은 언제였을까요?")


def test_route_wires_probe_quality_and_transition_glue():
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert "same_question_as_recent as _sqr" in src and "_klq(clean_reply)" in src and "_fmq(clean_reply)" in src
    assert "# 8-j." in src and "_render_anchor_for(current_target_sub)" in src
    assert "if _is_probe and not _is_anchor:" in src                 # 전환 턴은 질문 검사 제외
    assert 'v["anchor_missing"] = True' not in src                    # 앵커는 시스템이 붙인다
    assert '"state_leak"' in src and '"semrep"' in src and '"quote"' in src and '"bridge"' in src


# ── D. 앵커 렌더링 플래그 ──
def test_must_ask_covers_every_anchor_key():
    assert set(SUBCOMPETENCY_MUST_ASK) == set(SUBCOMPETENCY_ANCHOR_QUESTIONS)
    for k, v in SUBCOMPETENCY_MUST_ASK.items():
        assert 3 <= len(v) <= 4, k
        assert any(x.startswith("행동") for x in v) and any(x.startswith("시점") for x in v), k


def test_dict_mode_default_and_llm_off_without_flag(monkeypatch):
    monkeypatch.delenv("ANCHOR_RENDER", raising=False)
    assert AR.anchor_render_mode() == "dict"
    q, mode = asyncio.run(AR.render_anchor(None, "vision_sharing", recent_turns=[], role_summary=None))
    assert mode == "dict" and q == SUBCOMPETENCY_ANCHOR_QUESTIONS["vision_sharing"][0]
    monkeypatch.setenv("ANCHOR_RENDER", "llm")
    assert AR.anchor_render_mode() == "llm"
    q2, mode2 = asyncio.run(AR.render_anchor(None, "vision_sharing", recent_turns=[], role_summary=None))
    assert mode2 == "dict"      # llm 객체가 없으면 사전


def test_llm_mode_falls_back_when_judge_says_no(monkeypatch):
    monkeypatch.setenv("ANCHOR_RENDER", "llm")

    class _LLM:
        async def _generate_with_retry(self, prompt, **kw):
            if kw.get("call_type") == "anchor_render":
                return "최근에 팀의 방향을 새로 세우면서 반신반의하던 팀원을 직접 설득하신 일이 있으셨어요?"
            return "NO"
    q, mode = asyncio.run(AR.render_anchor(_LLM(), "vision_sharing", recent_turns=["a", "b"], role_summary="교육팀장"))
    assert mode == "fallback" and q == SUBCOMPETENCY_ANCHOR_QUESTIONS["vision_sharing"][0]

    class _LLM2(_LLM):
        async def _generate_with_retry(self, prompt, **kw):
            if kw.get("call_type") == "anchor_render":
                return "최근에 팀의 방향을 새로 세우면서 반신반의하던 팀원을 직접 설득하신 일이 있으셨어요?"
            return "YES"
    q2, mode2 = asyncio.run(AR.render_anchor(_LLM2(), "vision_sharing", recent_turns=["a", "b"], role_summary="교육팀장"))
    assert mode2 == "llm" and q2.endswith("?") and "비전 제시" not in q2

    class _LLM3(_LLM2):
        async def _generate_with_retry(self, prompt, **kw):
            if kw.get("call_type") == "anchor_render":
                return "비전 제시 및 공유와 관련해 항해의 나침반이 되어주신 순간이 있으셨어요?"   # 이름·은유 → 형식 불합격
            return "YES"
    q3, mode3 = asyncio.run(AR.render_anchor(_LLM3(), "vision_sharing", recent_turns=[], role_summary=None))
    assert mode3 == "fallback"
