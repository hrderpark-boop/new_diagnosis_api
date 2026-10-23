"""(2026-10-22 P2-3) 페르소나 복원 — 되받기 상한·관찰 문장·전환 다리·ALIGN 고정 다리 (LLM·DB 없음)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.data.competencies import SUBCOMPETENCY_ANCHOR_QUESTIONS, SUBCOMPETENCY_TOPIC_PHRASE  # noqa: E402
from diag_project.prompts.phase3a import layer3_state as L  # noqa: E402
from diag_project.services import output_guard as G  # noqa: E402
from diag_project.services.intro_messages import TRANSITION_BRIDGES, align_topic_bridge, transition_bridge  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER = "선임은 속도를 원했고 저는 준비를 택했어요. 그래서 두 달 뒤에 오픈했습니다."


def test_persona_lead_caps():
    assert G.persona_lead_cap("Ella (엘라)") == 2 and G.persona_lead_cap("Daniel (다니엘)") == 2
    assert G.persona_lead_cap("Jessica (제시카)") == 1 and G.persona_lead_cap("Lucas (루카스)") == 1
    assert G.persona_lead_cap("Olivia") == 2 and G.persona_lead_cap("Michael") == 2 and G.persona_lead_cap(None) == 2


def test_observation_sentence_uses_only_leader_nouns():
    assert G.is_observation("속도를 원하는 선임과 준비를 택한 리더님 사이였군요.", USER)
    assert not G.is_observation("마음이 무겁지 않으셨던 것 같네요.", USER)          # 발화에 없는 명사(마음)
    assert not G.is_observation("팀원들이 불안해하셨겠어요.", USER)


def test_cap_leads_prefers_observation():
    t = "쉽지 않은 전환이었겠어요. 속도를 원하는 선임과 준비를 택한 리더님 사이였군요. 그래도 잘 버티셨네요. 그 두 달 동안 무엇을 하셨어요?"
    out, n = G.cap_leads_persona(t, 1, USER)
    assert n == 2 and out == "속도를 원하는 선임과 준비를 택한 리더님 사이였군요. 그 두 달 동안 무엇을 하셨어요?"
    out2, n2 = G.cap_leads_persona(t, 2, USER)
    assert n2 == 1 and "리더님 사이였군요" in out2 and "그 두 달 동안" in out2
    assert G.cap_leads_persona("그때 무엇을 하셨어요?", 1, USER) == ("그때 무엇을 하셨어요?", 0)


def test_transition_bridges_three_per_persona_and_not_banned():
    for name, pool in TRANSITION_BRIDGES.items():
        assert len(pool) == 3, name
        for b in pool:
            assert not G.find_banned_tail(b) and not G.is_question(b), b
    assert transition_bridge("Jessica (제시카)", 4) == TRANSITION_BRIDGES["Jessica"][1]
    assert transition_bridge("없는코치", 0) == TRANSITION_BRIDGES["Ella"][0]


def test_align_topic_bridge_and_phrases():
    assert set(SUBCOMPETENCY_TOPIC_PHRASE) == set(SUBCOMPETENCY_ANCHOR_QUESTIONS)
    for k, v in SUBCOMPETENCY_TOPIC_PHRASE.items():
        assert v.endswith("쪽") and "제시" not in v and "사고" not in v, k        # 이름 노출 없이 설명어
    assert align_topic_bridge("vision_sharing") == "먼저 방향을 세우고 사람을 모으는 쪽부터 볼게요."
    # 설명어는 앵커 문장과 겹치지 않게 짧게(앵커 핵심어 '반신반의' 미포함)
    assert all(len(v) <= 20 and "반신반의" not in v for v in SUBCOMPETENCY_TOPIC_PHRASE.values())
    assert align_topic_bridge(None).startswith("먼저 ")
    body = "저희는 이렇게 봅니다.\n· 비전 제시 및 공유\n· 전략적 사고\n\n'효율'이라는 말씀, 그게 시험받았던 장면부터 들어보고 싶네요."
    out, n = G.strip_align_tail_statements(body)
    assert n == 1 and out.endswith("· 전략적 사고")


def test_align_guide_no_bridge_instruction():
    base = {"instruction_for_this_turn": "COMPETENCY_ALIGN", "chapter": "organization_management", "turn_count": 1,
            "events_collected": 0, "events_with_star_70": 0, "current_event_id": None, "current_event_star_coverage": None,
            "has_contrary_probe": False, "avoidance_count_in_chapter": 0, "first_subcompetency_name": "비전 제시 및 공유",
            "coach_persona": {"name": "Ella"}, "all_subcompetencies": ["비전 제시 및 공유", "전략적 사고"],
            "last_user_response": "조직을 효율적으로 관리하는 거요"}
    g = L._get_instruction_guide("COMPETENCY_ALIGN", base)
    assert "다리는 쓰지 않습니다" in g and "먼저 ~쪽부터 볼게요" in g
    assert "들어보고 싶네요" not in g.split("예시 서식")[1]      # 서식 예시에서 다리 줄 제거


def test_route_wiring():
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert "align_topic_bridge as _atb" in src and "strip_align_tail_statements as _sats" in src
    assert "transition_bridge as _tbr" in src and "cap_leads_persona as _clp" in src
    assert "max_statements=_cap_p" in src


def test_persona_lines_complete_and_structural():
    """(2026-10-22) 고정 문장 전부 페르소나별 변형 — 구조는 하나, 문장은 페르소나."""
    from diag_project.services.intro_messages import PERSONA_LINES, definition_question, pause_suggestion_text, persona_line
    keys = set(PERSONA_LINES["Ella"])
    assert set(PERSONA_LINES) == {"Ella", "Jessica", "Olivia", "Daniel", "Michael", "Lucas"}
    for p, d in PERSONA_LINES.items():
        assert set(d) == keys, p
        for k in ("role_q", "expect_q", "smalltalk_q", "result_a", "result_b", "quantify", "action", "one_more"):
            assert G.has_question(d[k]), (p, k)
        for v in d.values():
            assert not G.find_banned_tail(v)
    assert persona_line("Michael (마이클)", "action") == "좋습니다, 그때 리더님이 직접 움직이신 건 뭐였어요?"
    assert persona_line("Jessica", "action") == "리더님이 직접 하신 일은 무엇입니까?"
    assert persona_line("Ella", "action") == "그때 리더님은 직접 어떻게 하셨어요?"
    assert persona_line("없는코치", "role_q") == PERSONA_LINES["Ella"]["role_q"]          # 폴백 Ella
    assert definition_question("성과관리", "Lucas") == "리더님께서는 '성과관리'를 무엇이라고 정의하십니까?"
    assert "달려오셨습니다" in pause_suggestion_text(47, "Michael") and "47분째" in pause_suggestion_text(47, "Michael")
    assert G.result_fallback_question("두 달 걸렸어요", None, alt=1, persona="Jessica") == "결과는 어떻게 나왔습니까?"
    assert align_topic_bridge("delegation", None, "Lucas") == "먼저 맡기는 쪽부터요."


def test_rapport_fixed_question_binds_persona_name():
    """(2026-10-23 핫픽스) 9fad8ae 회귀: _pl_r("role_q") 가 persona_line 별칭이라 TypeError → 운영 라포 3턴 500. 이름을 묶은 호출자여야 한다."""
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert "def _pl_r(key: str, **fmt) -> str:" in src and "_persona_line_r(_persona_name_r, key, **fmt)" in src
    assert "import persona_line as _pl_r" not in src
    # 다른 별칭은 모두 (이름, 키) 두 인자로 부른다
    import re
    for alias in ("_pl_i", "_pl_q", "_pl_a", "_pl_om"):
        for m in re.finditer(alias + r"\(([^)]*)\)", src):
            assert "coach_persona" in m.group(1), (alias, m.group(0)[:80])
