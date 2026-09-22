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
    # (2026-09-22) 리드 삭제(trim_lead_sentences)는 폐지 — 판정 함수만 남는다(관찰용)


# ── 5) 넓이 하한 ──
def test_breadth_floor_all_when_four_or_fewer():
    assert T.min_explored_for(4) == 4 and T.min_explored_for(3) == 3
    assert T.min_explored_for(5) == 3 and T.min_explored_for(9) == 6
    assert ID.MIN_EXPLORED == {"organization_management": 4, "performance_management": 3,
                               "people_management": 6, "work_management": 3, "self_management": 3}
    assert T.chapter_turn_cap(ID.MIN_EXPLORED["organization_management"]) == 16
    for ch, m in ID.MIN_EXPLORED.items():
        assert T.chapter_turn_cap(m) < ID.MAX_TURNS[ch]


# ── 2026-09-17 Daniel 성과관리 재주행 6건 ──
CH = "organization_management"
def test_echo_requires_two_chunks_single_quote_allowed():
    from diag_project.services.style_tracker import echoes_user
    user = "팀원들이 마음속으로 진심으로 인정하는지는 모르겠습니다."
    # 한 어절 인용(연결 한 절)은 복창이 아니다
    assert not echoes_user("방금 말씀하신 '인정'과도 이어지는데요, 목표를 정할 때는 어떻게 하셨습니까?", user)
    # 어절 2개 이상 되풀이는 복창
    assert echoes_user("팀원들이 진심으로 인정하는지 모르겠다고 하셨습니다. 그다음은요?", user)


def test_bridge_keyword_and_bridged_anchor():
    kw = G.bridge_keyword("팀원들이 마음속으로 진심으로 인정하는지는 모르겠습니다.")
    assert kw and 2 <= len(kw) <= 6
    t = G.template_anchor_bridged("최근에 결과를 어떻게 확인하셨습니까?", "팀원들이 진심으로 인정하는지 모르겠습니다.")
    assert t.startswith("방금 말씀하신 '") and t.endswith("확인하셨습니까?") and t.count("?") == 1
    assert G.template_anchor_bridged("질문?", "") == G.template_anchor("질문?")


def test_result_probe_pool_rotates_without_repeat():
    st = {}
    seen = []
    for _ in range(len(T.RESULT_PROBE_POOL)):
        q, st = T.pick_result_probe(st, CH)
        seen.append(q)
    assert len(set(seen)) == len(T.RESULT_PROBE_POOL)            # 챕터 안 무반복
    assert T.used_result_probes(st, CH) == seen
    q2, st = T.pick_result_probe(st, CH)                           # 다 쓰면 처음부터
    assert q2 == T.RESULT_PROBE_POOL[0]
    assert all("그렇게 하니" not in q for q in T.RESULT_PROBE_POOL)


def test_repeated_result_probe_detected():
    used = ["그 뒤로 달라진 게 있었습니까?"]
    assert G.find_repeated_result_probe("그렇게 하니까 어떻게 됐습니까?", []) is not None   # 상투형
    assert G.find_repeated_result_probe("그때 그 뒤로 달라진 게 있었습니까?", used) is None  # 다른 문장
    assert G.find_repeated_result_probe("그 뒤로 달라진 게 있었습니까?", used) is not None  # 같은 문장 반복
    assert G.find_repeated_result_probe("결과를 어떻게 확인하셨습니까?", used) is None


def test_absence_keywords_extended():
    from diag_project.services.avoidance_detector import detect_absence_statement
    for t in ("그때그때 해결했고 특별한 것 없음", "딱히 기억나는 건 없습니다", "특별한 것은 없었어요", "그때그때 처리했죠"):
        assert detect_absence_statement(t), t
    assert not detect_absence_statement("그때그때 상황을 보며 팀원들과 우선순위를 다시 정하고 두 달에 걸쳐 새 체계를 안착시켰습니다.")


def test_rapport_role_turn_and_context_state():
    assert ID._force_rapport_category(1) == "담당업무" and ID._force_rapport_category(2) == "기대"
    import inspect
    from diag_project.routes import diagnoses as D
    src = inspect.getsource(D)
    assert "ROLE_ASK" in src and "participant_context" in src and "어떤 일을 맡고 계신지" in src


def test_praise_list_covers_wrapup_phrases_and_wrapup_is_template():
    for p in ("인상적입니다", "매우 인상 깊습니다", "리더님의 면모", "기준이 선명하게 그려지는 듯합니다", "돋보이는 결정"):
        assert G.find_praise(p), p
    import inspect
    from diag_project.routes import diagnoses as D
    src = inspect.getsource(D)
    assert "여기까지 충분히 들었습니다. 이제 '{chapter_to_topic(_next_ch)}'로 이어가 보겠습니다." in src
    # ALIGN 은 리드 교정 대상에서 제외(정의·목록이 지워지던 버그)
    assert 'instruction_used not in ("COMPETENCY_ALIGN", "CHAPTER_OPENING")' in src


def test_bridge_rule_in_style_hints_and_analysis_flag():
    from diag_project.services.style_tracker import format_style_constraints
    sc = {"forbid_recap": True, "forbid_ne_opening": False}
    for n in ("Daniel (다니엘)", "Jessica (제시카)", "Lucas (루카스)"):
        t = format_style_constraints(sc, n)
        assert "연결 한 절" in t and "한 어절" in t, n
    from diag_project.llm_service import GeminiService
    tmpl = GeminiService._build_sub_scores_json_template(None, ["목표설정 및 공유"])
    assert "consistency_flag" in tmpl


# ── 2026-09-18 (a) 재생성 줄이기: 연결 절 예외·꼬리 블록·negative example ──
def test_bridge_clause_is_not_recap():
    from diag_project.services.style_tracker import is_recap_opening, compute_style_constraints
    bridge = "방금 말씀하신 '인정'과도 이어지는데요, 목표를 정할 때는 어떻게 하셨습니까?"
    assert not is_recap_opening(bridge)
    assert is_recap_opening("말씀하신 내용, 잘 들었습니다. 그다음은요?")     # 인용 없는 '말씀하신' 은 그대로 되받기
    # 직전 두 턴이 연결 절이면 이번 턴 요약 금지가 걸리지 않는다(불필요한 금지 → 재생성 방지)
    sc = compute_style_constraints([bridge, "말씀하신 '지표'와 연결해 여쭙니다. 누가 정했습니까?"], ["인정하는지 모르겠습니다", "지표가 문제였죠"])
    assert sc["forbid_recap"] is False


def test_style_tail_block_placed_before_latest_user_message():
    from diag_project.prompts.phase3a.layer3_state import build_style_tail, format_turn_state_for_llm
    st = {"chapter": CH, "turn_count": 5, "events_collected": 1, "events_with_star_70": 0,
          "current_event_id": None, "current_event_star_coverage": None, "has_contrary_probe": False,
          "avoidance_count_in_chapter": 0, "all_subcompetencies": [], "explored_subcompetencies": [],
          "unexplored_subcompetencies": [], "asked_in_chapter": [], "instruction_for_this_turn": "STAR_INCOMPLETE",
          "coach_persona": {"name": "Daniel (다니엘)"}, "style_constraints": {"forbid_ne_opening": True, "forbid_recap": True},
          "style_at_tail": True}
    mid = format_turn_state_for_llm(st)
    tail = build_style_tail(st)
    assert "이번 턴 문체 제약" not in mid and "마지막 확인" in tail
    assert "되풀이하지" in tail and "요약 되받기 금지" not in tail   # (2026-09-22) 자르지 않고 한 줄 지시만
    import inspect
    from diag_project.llm_service import GeminiService
    src = inspect.getsource(GeminiService.generate_phase3a_interaction)
    assert src.index('f"{_tail}"') < src.index('[Latest User Message]')


def test_sub_name_mention_stripped_in_non_anchor_turn():
    t = "앞서 리더님께서 말씀해주신 '변화관리'와 관련하여, 그 노력이 어떤 결과로 이어졌는지 여쭤봐도 되겠습니까?"
    out, n = G.strip_sub_name_mentions(t, NAMES)
    assert n >= 1 and "변화관리" not in out and out.endswith("되겠습니까?")
    same, n0 = G.strip_sub_name_mentions("그때 팀은 어떻게 반응했습니까?", NAMES)
    assert n0 == 0 and same.startswith("그때")


def test_bridge_keyword_prefers_noun_over_verb_fragment():
    assert G.bridge_keyword("팀원들의 주인의식이 향상되었고 기획안의 목적이 명확해졌습니다.") not in ("향상되었고", "명확해졌")
    kw = G.bridge_keyword("팀원들의 주인의식이 향상되었고 기획안의 목적이 명확해졌습니다.")
    assert kw and not G._VERBISH_END.search(kw)
    assert G.has_question("조직관리 영역 이야기는 이쯤에서 마무리하겠습니다.") is False
    assert G.has_question("그 뒤로 달라진 게 있었습니까?") is True


# ── 2026-09-21 사람관리 사고 재발 방지: 하드 교정의 질문·연결 절 보존 ──
def test_strip_transition_keeps_text_when_only_transition_remains():
    from diag_project.services.output_guard import strip_transition_sentences, has_question
    txt = "네, 알겠습니다. 그럼 다음 챕터로 넘어가겠습니다."
    out, n = strip_transition_sentences(txt)
    # 호출자(8-i)가 프로브 턴이면 템플릿 앵커로 간다 — 함수 자체는 질문이 없으면 원문 보존 계약
    assert not has_question(out)


def test_guard_block_source_contract_2026_09_21():
    """8-i 소스 계약: 재생성 키 = names/off_target/no_question, 결과 질문 풀 폴백 없음, ABSENCE_PROBE 제외."""
    import inspect
    from diag_project.routes import diagnoses as d
    src = inspect.getsource(d._submit_message_phase3a)
    i = src.index("# 8-i.")
    j = src.index("# 8-h.")
    blk = src[i:j]
    assert '_REGEN_KEYS = {"names", "off_target", "no_question", "same_question"}' in blk
    assert 'instruction_used != "ABSENCE_PROBE"' in blk
    assert "질문 없는 출력 → 결과 질문 대체" not in blk           # 질문 없는 출력 → 풀 대체 폐기
    assert "template_anchor_bridged(_tgt_q, request.content)" in blk
    assert "trim_lead_sentences(" not in blk          # (2026-09-22) 되받기 리드 삭제 폐지
    assert "strip_transition_sentences(" not in blk   # 전환 문장 삭제 폐지 — 관찰만


def test_bridge_keyword_skips_adjective_and_verb_fragments_and_picks_josa():
    from diag_project.services.output_guard import bridge_keyword, bridge_prefix
    kw = bridge_keyword("새로운 방향성에 대해 우려를 표명하는 팀원들과 개별 면담을 진행하며 데이터를 공유했습니다.")
    assert kw not in ("새로운", "표명하", "진행하"), kw
    assert bridge_keyword("네, 알겠습니다. 다음 챕터도 편하게 말씀해 주세요.") != "말씀해"
    assert bridge_prefix("인정").startswith("방금 말씀하신 '인정'과도")
    assert bridge_prefix("지표").startswith("방금 말씀하신 '지표'와도")


def test_strip_sub_name_mentions_leaves_partial_match_inside_long_quote():
    from diag_project.services.output_guard import strip_sub_name_mentions
    txt = "방금 말씀하신 '프로세스 표준화 작업이 정착'되는 과정에서 어떤 행동을 하셨습니까?"
    out, n = strip_sub_name_mentions(txt, ["프로세스 표준화", "변화관리(변화지향)"])
    assert n == 0 and out == txt
    out2, n2 = strip_sub_name_mentions("'변화관리'와 관련하여, 그때 어떻게 하셨습니까?", ["변화관리(변화지향)"])
    assert n2 >= 1 and out2.startswith("그때"), out2
    out3, n3 = strip_sub_name_mentions("변화관리 측면에서 그때 어떻게 하셨습니까?", ["변화관리(변화지향)"])
    assert n3 == 1 and out3.startswith("그때"), out3


def test_same_question_as_previous_ignores_bridge_and_hedges():
    from diag_project.services.output_guard import same_question_as_previous
    prev = "방금 말씀하신 '단순히'와도 이어지는데요, 그 결에서 이어 여쭙니다만, 혹 지쳐서 손을 놓으려던 팀원을 다시 움직이게 하셨던 경험이 있으셨습니까?"
    cur = "방금 말씀하신 '주도성'과도 이어지는데요, 혹시 지쳐서 손을 놓으려던 팀원을 다시 움직이게 하셨던 경험이 있으셨습니까?"
    assert same_question_as_previous(cur, prev)
    assert same_question_as_previous("그때 팀원들은 어떻게 반응했습니까?", prev) is None


def test_absence_keywords_do_not_match_affirmative_delegation():
    from diag_project.services.avoidance_detector import detect_absence_statement
    assert not detect_absence_statement("작은 성취를 맛볼 수 있는 마일스톤을 쪼개어 단계별로 권한을 위임한 적이 있습니다. 매주 1on1 미팅으로 방향을 잡아 주었습니다.")
    assert detect_absence_statement("권한을 위임한 적이 없습니다.")


def test_bridge_keyword_ignores_curly_quotes_and_markdown():
    from diag_project.services.output_guard import bridge_keyword
    kw = bridge_keyword("팀원들에게 ‘실패해도 안전한 환경’을 제공하여 **주도성**을 키웠습니다.")
    assert "’" not in kw and "*" not in kw, kw


def test_strip_sub_name_mentions_replaces_quoted_name_with_josa_fix():
    from diag_project.services.output_guard import strip_sub_name_mentions
    out, n = strip_sub_name_mentions("실제로 팀의 '팀워크'나 장기적인 성과에 어떤 변화가 있었습니까?", ["팀워크 촉진(협업)", "팀워크"])
    assert n >= 1 and "그 부분이나 장기적인" in out, out
    out2, _ = strip_sub_name_mentions("'권한위임'를 하실 때 어떤 기준이었습니까?", ["권한위임"])
    assert "그 부분을" in out2, out2


def test_guard_fallback_avoids_repeating_anchor_source_contract():
    import inspect
    from diag_project.routes import diagnoses as d
    src = inspect.getsource(d._submit_message_phase3a)
    blk = src[src.index("# 8-i."):src.index("# 8-h.")]
    assert "def _anchor_fallback()" in blk and "_recent_coach_texts" in blk
    # 교정 폴백은 전부 _anchor_fallback 을 지난다(직전 2턴에 나간 앵커 반복 방지)
    assert blk.count("template_anchor_bridged(_tgt_q, request.content)") == 2  # _anchor_fallback 내부 2곳뿐
