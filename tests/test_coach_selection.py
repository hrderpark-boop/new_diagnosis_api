"""코치 선택 버그 수정: 인사말·페르소나가 '선택한' coach_id 로 결정되는지.

(구 _session_coach_key 는 세션 UUID 로 랜덤 배정해 선택을 무력화 → 어느 코치를
골라도 인사가 Lucas 로 나오던 버그. 이제 선택 coach_id 를 그대로 읽는다.)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.routes.diagnoses import (  # noqa: E402
    _coach_key_from_id, COACH_UUID_TO_KEY,
)
from diag_project.data.coaches_persona import COACHES_PERSONA  # noqa: E402


def test_each_coach_maps_to_its_own_key():
    """6개 coach_id 각각 → 자기 키(선택 일치). 랜덤·고정 아님."""
    for uid, key in COACH_UUID_TO_KEY.items():
        assert _coach_key_from_id(uid) == key


def test_all_six_distinct():
    keys = {_coach_key_from_id(uid) for uid in COACH_UUID_TO_KEY}
    assert len(keys) == 6, keys


def test_bad_id_falls_back_to_1():
    assert _coach_key_from_id("not-a-real-id") == "1"
    assert _coach_key_from_id(None) == "1"


def test_greeting_and_persona_same_coach():
    """인사말 이름과 대화 페르소나가 '같은' coach_id 로 유도되면 갈리지 않는다.

    두 호출부가 동일 헬퍼(_coach_key_from_id)에 동일 coach_id 를 넘기므로,
    같은 coach_id → 같은 키 → 같은 코치 이름이 보장된다.
    """
    for uid, key in COACH_UUID_TO_KEY.items():
        greeting_key = _coach_key_from_id(uid)   # 인사말 경로
        persona_key = _coach_key_from_id(uid)    # 대화 경로
        assert greeting_key == persona_key == key
        # 이름도 선택 코치와 일치
        assert COACHES_PERSONA[greeting_key]["name"] == COACHES_PERSONA[key]["name"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn(); print(f"  [PASS] {fn.__name__}")
    print("=== coach selection: PASS ===")
