"""P10 (2026-11-10) 대화 소수정 — 상태 보고문 변형·사례 번호 금지·요청형 받는 문장(단위 테스트만)."""
import inspect


def test_state_report_variants():
    from diag_project.services.leak_lexicon import find_state_report
    for s in ("이 부분은 충분히 짚어봤습니다.", "성과관리를 목표를 함께 세우고 끝까지 이끄는 일로 보신다는 말씀을 짚어봤습니다.", "충분히 살펴봤습니다."):
        assert find_state_report(s), s
    assert not find_state_report("그 기준을 한 번 더 짚어 주시겠습니까?") and not find_state_report("두 축을 함께 짚으셨군요.")


def test_case_numbers_become_content_references():
    from diag_project.services.output_guard import rewrite_case_numbers
    out, n = rewrite_case_numbers("사례 1에서 두 분을 따로 부르셨고, 두 번째 사례에서는 대표님께 안을 가져가셨습니다.", {1: "교육 체계 개편", 2: "AI 도구"})
    assert n == 2 and out == "아까 말씀하신 교육 체계 개편 건에서 두 분을 따로 부르셨고, 아까 말씀하신 AI 도구 건에서는 대표님께 안을 가져가셨습니다."
    assert rewrite_case_numbers("앞서 사례 2번에서 말씀하신 기준과 같습니까?", {}) == ("앞서 말씀하신 이야기에서 말씀하신 기준과 같습니까?", 1)
    assert rewrite_case_numbers("첫 사례에서 쓰신 방법입니다.", {1: "파일럿"})[0] == "아까 말씀하신 파일럿 건에서 쓰신 방법입니다."
    assert rewrite_case_numbers("그 사례에서 가장 먼저 하신 일은 무엇입니까?", {1: "x"}) == ("그 사례에서 가장 먼저 하신 일은 무엇입니까?", 0)   # 번호 없는 지칭은 그대로
    assert rewrite_case_numbers("리더님이 '사례 1번 자료'라고 하셨습니다.", {})[1] == 0                                              # 따옴표 안(리더 말)은 그대로
    from diag_project.prompts.phase3a import layer1_system
    src = inspect.getsource(__import__("diag_project.routes.diagnoses", fromlist=["x"]))
    assert "번째 사례에서 이쪽 이야기가" not in src and "rewrite_case_numbers" in src and "번호가 아니라 리더가 쓴 말로" in inspect.getsource(layer1_system)


def test_request_statement_before_question_is_dropped():
    from diag_project.services.output_guard import drop_request_statements, is_request_statement
    t = "그 대답에서 두 분이 어떤 표정이나 말로 받아들였는지 조금 더 듣고 싶습니다. 그 선택을 가른 기준 하나를 꼽으면 무엇입니까?"
    assert is_request_statement("그 대답에서 두 분이 어떤 표정이나 말로 받아들였는지 조금 더 듣고 싶습니다.")
    assert drop_request_statements(t) == ("그 선택을 가른 기준 하나를 꼽으면 무엇입니까?", 1)
    keep = "두 분을 따로 불러 이유부터 들으셨군요. 그 자리에서 처음 꺼내신 말은 무엇이었습니까?"
    assert drop_request_statements(keep) == (keep, 0) and not is_request_statement("두 분을 따로 불러 이유부터 들으셨군요.")
    only = "두 분을 따로 부르셨군요. 그 자리의 장면을 조금 더 듣고 싶습니다."
    assert drop_request_statements(only) == (only, 0)                                # 질문이 없으면 그 요청이 이 턴의 질문 — 지우지 않는다
    src = inspect.getsource(__import__("diag_project.routes.diagnoses", fromlist=["x"]))
    assert "_irs_s(x)" in src and "drop_request_statements" in src
