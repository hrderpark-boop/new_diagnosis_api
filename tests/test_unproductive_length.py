"""M4: 짧은 성실 답변은 '비생산 응답(회피)'이 아니다.

is_unproductive_response 가 check_avoidance 의 '10자 미만 = 회피' 길이 조건을
그대로 써서 "네"/"맞아요" 가 avoidance_count 를 올리고, 3회면 no_yield_forced
(유의미한 진단 불가 멘트)로 챕터가 닫히던 오판을 고정한다.
"""
from diag_project.services.avoidance_detector import is_unproductive_response


def test_short_affirmatives_are_not_unproductive():
    for t in ["네", "네.", "맞아요", "맞습니다", "직접 했어요", "제가요"]:
        assert is_unproductive_response(t) is False, t


def test_avoidance_keywords_still_unproductive_regardless_of_length():
    for t in ["모르겠어요", "기억 안 나요", "글쎄요", "잘 모르겠습니다 그건"]:
        assert is_unproductive_response(t) is True, t


def test_empty_is_unproductive():
    assert is_unproductive_response("") is True
    assert is_unproductive_response("   ") is True
    assert is_unproductive_response(None) is True


def test_deflection_and_rush_still_unproductive():
    assert is_unproductive_response("팀원들 때문이죠 뭐") is True
    assert is_unproductive_response("빨리 합시다") is True
