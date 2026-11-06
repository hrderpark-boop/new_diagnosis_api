"""(2026-11-06 P6) 사례 단위 게이트 — 근거 인용이 속한 사례 전체를 게이트가 보고, 자기 챕터 근거 우선, 한 사례가 올린 칸 수 집계, 반복 인용 표시."""
import asyncio
import uuid
from types import SimpleNamespace as NS

from diag_project.services import episode_context as EC
from diag_project.services import level_gate as LG

CH_O, CH_P = "organization_management", "performance_management"


def _episodes():
    e1, e2 = uuid.uuid4(), uuid.uuid4()
    msgs = [
        NS(role="model", content="여는 질문", chapter=CH_O, event_id=None),
        NS(role="user", content="작년 3월 본부 지시로 교육 체계를 바꿀 때 두 강사가 반대했어요.", chapter=CH_O, event_id=e1),
        NS(role="model", content="그때 무엇을?", chapter=CH_O, event_id=e1),
        NS(role="user", content="두 사람을 따로 불러서 먼저 이유를 들었고, 한 과정만 두 달 파일럿으로 돌리자고 제안했습니다.", chapter=CH_O, event_id=e1),
        NS(role="user", content="참여율을 핵심 목표로 잡고 만족도도 함께 관리하자고 제안했습니다. 제가 먼저 두 지표를 어떻게 볼지 기준을 제안했어요.", chapter=CH_P, event_id=e2),
    ]
    events = [
        NS(id=e1, chapter=CH_O, summary="사례 1: 작년 3월 본부 지시", situation="작년 3월…", action="따로 불러서…", result=None, mapped_subcompetency="변화관리(변화지향), 비전 제시 및 공유"),
        NS(id=e2, chapter=CH_P, summary="사례 1: 참여율", situation=None, action="참여율을 핵심 목표로…", result=None, mapped_subcompetency="목표설정 및 공유"),
        NS(id=uuid.uuid4(), chapter=CH_P, summary="보완: 아까 그 일", situation="아까 그 일에서 표로 정리", action=None, result=None, mapped_subcompetency="성과지표 관리(KPI)"),
    ]
    return msgs, events


def test_build_index_maps_leader_turns_and_falls_back_to_slots():
    msgs, events = _episodes()
    idx = EC.build_episode_index(msgs, events)
    assert [e["label"] for e in idx] == ["조직관리 사례 1", "성과관리 사례 1", "성과관리 보완"]
    assert idx[0]["leader_texts"][0].startswith("작년 3월") and len(idx[0]["leader_texts"]) == 2 and idx[0]["kind"] == "episode"
    assert idx[2]["kind"] == "sweep" and idx[2]["leader_texts"] == ["아까 그 일에서 표로 정리"]      # 태깅 없음 → 슬롯 인용 폴백
    assert idx[0]["mapped"] == ["변화관리(변화지향)", "비전 제시 및 공유"]


def test_find_episode_prefers_own_chapter_and_loose_match():
    msgs, events = _episodes()
    idx = EC.build_episode_index(msgs, events)
    q = "(조직관리 대화에서) 두 사람을 따로 불러서 먼저 이유를 들었고"
    assert EC.find_episode_for_quote(q, idx, prefer_chapter=CH_P)["label"] == "조직관리 사례 1"   # 출처 표기 떼고 매핑
    assert EC.find_episode_for_quote("제가 먼저 두 지표를 어떻게 볼지 기준을 제안했어요", idx, CH_P)["label"] == "성과관리 사례 1"
    assert EC.find_episode_for_quote("짧음", idx) is None and EC.find_episode_for_quote("전혀 다른 문장입니다 정말로", idx) is None
    eps = EC.episodes_for_evidence(["두 사람을 따로 불러서 먼저 이유를", "한 과정만 두 달 파일럿으로"], idx, CH_O)
    assert len(eps) == 1 and EC.episode_hash(eps) and EC.episode_hash(eps) != EC.episode_hash(idx[1:2]) and EC.episode_hash([]) == ""


def test_gate_body_has_episode_block_once_and_reference_lines():
    msgs, events = _episodes()
    idx = EC.build_episode_index(msgs, events)
    ref = LG.level_reference(CH_O, "변화관리(변화지향)")
    items = [{"sub_name": "변화관리(변화지향)", "evidence": ["두 사람을 따로 불러서 먼저 이유를 들었고"], "claimed_level": 3, "ref": ref, "episodes": [idx[0]]},
             {"sub_name": "비전 제시 및 공유", "evidence": ["한 과정만 두 달 파일럿으로 돌리자고 제안했습니다"], "claimed_level": 2, "ref": ref, "episodes": [idx[0]]},
             {"sub_name": "전략적 사고", "evidence": ["e"], "claimed_level": 2, "ref": ref, "episodes": []}]
    block = LG._episodes_block_for(items)
    body = LG._build_gate_body(items)
    assert block.count("[사례 A]") == 1 and "조직관리 사례 1" in block and "[사례 B]" not in block      # 같은 사례는 한 번
    assert body.count("[사례 참조] 위 인용은 사례 A 의 일부다") == 2 and "[3] 하위역량: 전략적 사고" in body
    assert "[사례 참조]" not in body.split("[3] 하위역량")[1]                                      # 사례 없는 항목엔 참조 줄 없음
    assert "7. (사례 단위 판정)" in LG.GATE_SYSTEM and LG.GATE_PROMPT_VERSION == "2026-11-06.v4-scope"
    # 캐시 키: 사례 해시가 성분
    h = EC.episode_hash([idx[0]])
    assert LG._cache_key(CH_O, "s", ["e"], 2, "claude", h) != LG._cache_key(CH_O, "s", ["e"], 2, "claude", "")
    assert LG._persist_key(CH_O, "s", ["e"], 2, "claude", h) != LG._persist_key(CH_O, "s", ["e"], 2, "claude", "")


def test_gate_call_passes_episode_block_as_third_arg_and_votes_merge(monkeypatch):
    """gate_verify_levels: 3인자 콜러블에는 (본문, 지시, 사례 블록), 2인자에는 사례 블록을 본문 앞에 이어 붙인다."""
    msgs, events = _episodes()
    idx = EC.build_episode_index(msgs, events)
    monkeypatch.setenv("GATE_VOTES", "1")
    LG._GATE_CACHE.clear()
    seen = {}

    async def llm3(body, system, ep_block):
        seen["ep"] = ep_block; seen["body"] = body
        return '{"results": [{"idx": 1, "supported_level": 3, "category": "구체행동", "reason": "사례 전체에서 파일럿 제안"}]}'
    measured = {"변화관리(변화지향)": {"evidence": ["두 사람을 따로 불러서 먼저 이유를 들었고"], "claimed_level": 3, "episodes": [idx[0]]}}
    out = asyncio.run(LG.gate_verify_levels(CH_O, measured, llm3, provider="claude"))
    assert out["변화관리(변화지향)"]["verified_level"] == 3 and "[사례 A]" in seen["ep"] and "[사례 참조]" in seen["body"]

    async def llm2(body, system):
        seen["body2"] = body
        return '{"results": [{"idx": 1, "supported_level": 2, "category": "구체행동", "reason": "r"}]}'
    LG._GATE_CACHE.clear()
    measured2 = {"비전 제시 및 공유": {"evidence": ["한 과정만 두 달 파일럿으로 돌리자고 제안했습니다"], "claimed_level": 2, "episodes": [idx[0]]}}
    out2 = asyncio.run(LG.gate_verify_levels(CH_O, measured2, llm2, provider="claude"))
    assert out2["비전 제시 및 공유"]["verified_level"] == 2 and seen["body2"].startswith("[사례 전문") and "[사례 A]" in seen["body2"]


def test_prioritize_own_chapter_and_quote_chapters():
    turns = [(CH_O, "두 사람을 따로 불러서 먼저 이유를 들었고 파일럿을 제안했습니다"), (CH_P, "참여율을 핵심 목표로 잡자고 제안했습니다")]
    ev = ["참여율을 핵심 목표로 잡자고 제안했습니다", "(조직관리 대화에서) 두 사람을 따로 불러서 먼저 이유를 들었고", "출처를 알 수 없는 문장입니다 정말"]
    kept, cross = EC.prioritize_own_chapter(ev, CH_P, turns)
    assert kept == [ev[0], ev[2]] and cross == [ev[1]]                      # 자기 챕터 근거 있음 → 교차 제외, 출처 불명은 유지
    kept2, cross2 = EC.prioritize_own_chapter([ev[1]], CH_P, turns)
    assert kept2 == [ev[1]] and cross2 == []                                # 자기 챕터 근거 없음 → 교차 유지
    assert EC.quote_chapters(ev[1], turns) == [CH_O] and EC.quote_chapters("짧다", turns) == []


def test_episode_lift_and_duplicate_display():
    msgs, events = _episodes()
    idx = EC.build_episode_index(msgs, events)
    q = "두 사람을 따로 불러서 먼저 이유를 들었고"
    details = {
        CH_O: {"sub_ledger": {"변화관리(변화지향)": {"measured": True, "level": 3, "evidence": [q]},
                              "비전 제시 및 공유": {"measured": True, "level": 3, "evidence": ["한 과정만 두 달 파일럿으로 돌리자고 제안했습니다"]},
                              "전략적 사고": {"measured": True, "level": 2, "evidence": [q]}},
               "reasoning_process": {"2_action": {"description": "d", "quotes": [q, "다른 인용 문장 하나 더 있습니다"]}}},
        CH_P: {"sub_ledger": {"문제해결": {"measured": True, "level": 3, "evidence": [f"(조직관리 대화에서) {q}"]},
                              "성과지표 관리(KPI)": {"measured": True, "level": 3, "evidence": ["제가 먼저 두 지표를 어떻게 볼지 기준을 제안했어요"]}},
               "reasoning_process": {"2_action": {"description": "d", "evidence": [q]}}},
    }
    lift = EC.annotate_episode_lift(details, idx)
    assert lift["조직관리 사례 1"] == ["조직관리/변화관리(변화지향)", "조직관리/비전 제시 및 공유", "성과관리/문제해결"]   # Lv.2 칸은 세지 않는다
    assert lift["성과관리 사례 1"] == ["성과관리/성과지표 관리(KPI)"]
    assert details[CH_O]["sub_ledger"]["전략적 사고"]["episode"] == "조직관리 사례 1"
    assert EC.lift_warnings(lift) == ["조직관리 사례 1: 3칸 — 조직관리/변화관리(변화지향), 조직관리/비전 제시 및 공유, 성과관리/문제해결"]
    n = EC.dedupe_quotes_display(details)
    assert n == 4                                                                    # q 가 다섯 번(S/A/R 2 + 칸 3) → 두 번째부터 네 번 표시
    assert details[CH_O]["reasoning_process"]["2_action"]["quotes_display"][0] == q
    assert details[CH_O]["sub_ledger"]["전략적 사고"]["evidence_display"][0].startswith("(위 사례와 동일) 두 사람을 따로 불러서")
    assert details[CH_P]["sub_ledger"]["문제해결"]["evidence_display"][0].startswith("(위 사례와 동일)")
    assert details[CH_P]["sub_ledger"]["문제해결"]["evidence"][0].startswith("(조직관리 대화에서)")   # 원본 보존
    assert details[CH_P]["sub_ledger"]["성과지표 관리(KPI)"]["evidence_display"][0].startswith("제가 먼저")


def test_pipeline_wiring_p6():
    import inspect
    from diag_project import llm_service as L
    from diag_project.routes import reports as R
    src = inspect.getsource(L.GeminiService._run_level_gate)
    assert "prioritize_own_chapter" in src and '"episodes": _efe(' in src
    src2 = inspect.getsource(L.GeminiService.generate_diagnosis_result)
    assert "annotate_episode_lift" in src2 and "dedupe_quotes_display" in src2 and '_cov["episode_lift"]' in src2
    assert "build_episode_index(messages, events, store)" in inspect.getsource(R.load_analysis_inputs)
    assert "규칙 3-B" in inspect.getsource(L.GeminiService._analyze_single_competency) and "'성과지표 관리(KPI)' 칸의 근거로도" in inspect.getsource(L.GeminiService._analyze_single_competency)
    assert L._DEEP_PROMPT_VERSION_CLAUDE.startswith("2026-11-06")


# ── P6 승인 반영(2026-11-06): (가) 같은 챕터 사례만 묶기 · Lv.4 범위 조건 ──────────────────────────────────
def test_episodes_for_cell_combines_only_same_chapter_and_single_cross():
    msgs, events = _episodes()
    idx = EC.build_episode_index(msgs, events)
    own_q = ["두 사람을 따로 불러서 먼저 이유를 들었고", "한 과정만 두 달 파일럿으로 돌리자고 제안했습니다"]
    cross_q = "참여율을 핵심 목표로 잡고 만족도도 함께 관리하자고 제안했습니다"
    # 자기 챕터 사례 + 교차 사례가 섞이면 자기 챕터 사례만 남는다
    eps = EC.episodes_for_cell(own_q + [cross_q], idx, CH_O)
    assert [e["label"] for e in eps] == ["조직관리 사례 1"]
    # 자기 챕터 사례가 없으면 교차 사례 1건만(단독 근거)
    eps2 = EC.episodes_for_cell([cross_q, "아까 그 일에서 표로 정리"], idx, CH_O)
    assert len(eps2) == 1 and eps2[0]["chapter"] == CH_P
    import inspect
    from diag_project import llm_service as L
    assert "episodes_for_cell as _efe" in inspect.getsource(L.GeminiService._run_level_gate)
    assert "8. (사례 묶기)" in LG.GATE_SYSTEM and "다른 사례와 합쳐 요건을 채우지 않는다" in LG.GATE_SYSTEM


def test_scope_fix_caps_team_internal_lv4_to_lv3_p6b_teamwork_reasons():
    """p6b 2회차 팀워크 촉진(협업) 3→4 의 게이트 사유 2건을 고정 — 강사·운영·기획 합동 리뷰는 팀 안 장치라 Lv.3 상한."""
    r1 = "강사·운영·기획 사이의 탓하기를 풀려고 격주 합동 리뷰라는 협업 구조를 만들었고 상호 칭찬 규칙을 넣었다. 자료 지연이 사라지고 강사가 개선안을 먼저 가져오는 등 협업 문화로 정착해 Lv.4 협의체 주도에 부합한다."
    r2 = "강사·운영·기획이 함께하는 격주 합동 리뷰를 직접 만들어 운영했고, 그 결과 자료 지연이 사라지고 강사가 먼저 개선안을 가져왔다. 부서·직군 간 협의체를 주도한 Lv.4 행동에 부합한다."
    for r in (r1, r2):
        v, fixed, note = LG.scope_fix(4, r)
        assert (v, fixed) == (3, True) and "팀 안 장치" in note
    # 표 병합: 두 표 모두 3 → 3
    m = LG.merge_votes([{"verified_level": 3, "category": "구체행동", "reason": r1, "downgraded": True, "dropped": False, "pending": False},
                        {"verified_level": 3, "category": "구체행동", "reason": r2, "downgraded": True, "dropped": False, "pending": False}], 4)
    assert m["verified_level"] == 3
    # 팀 밖 범위가 사유에 있으면 Lv.4 유지
    assert LG.scope_fix(4, "타 부서 세 곳과 월례 합의체를 만들어 운영 기준을 통일했다.") == (4, False, "")
    assert LG.scope_fix(4, "전사 교육 체계를 설계해 본부별로 전파했다.")[0] == 4
    # Lv.3 이하는 손대지 않는다
    assert LG.scope_fix(3, r1) == (3, False, "") and LG.scope_fix(None, r1) == (None, False, "")
    assert "9. (Lv.4 범위)" in LG.GATE_SYSTEM and "Lv.3 이 상한" in LG.GATE_SYSTEM and LG.GATE_PROMPT_VERSION == "2026-11-06.v4-scope"


def test_scope_fix_applied_in_judge_batch(monkeypatch):
    monkeypatch.setenv("GATE_VOTES", "1")
    LG._GATE_CACHE.clear()
    ref = LG.level_reference("people_management", "팀워크 촉진(협업)")

    async def llm(body, system):
        return '{"results": [{"idx": 1, "supported_level": 4, "category": "구체행동", "reason": "강사·운영·기획이 함께하는 격주 합동 리뷰를 만들어 협업 문화로 정착시켰다."}]}'
    out = asyncio.run(LG.gate_verify_levels("people_management", {"팀워크 촉진(협업)": {"evidence": ["격주 합동 리뷰를 만들었어요"], "claimed_level": 4}}, llm, provider="claude"))
    v = out["팀워크 촉진(협업)"]
    assert v["verified_level"] == 3 and v.get("scope_fix") is True and v["downgraded"] is True
