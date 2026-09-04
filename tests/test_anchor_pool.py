"""item4: CHAPTER_OPENING 앵커 첫 질문이 챕터마다 다른 틀(무반복·결정론)인지 +
BEI 제약(시점·은유없음)을 구조적으로 지키는지 고정 테스트."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.intro_messages import (  # noqa: E402
    build_chapter_opening_with_user_def as _open, _ANCHOR_FRAMES,
)
from diag_project.data.competencies import COMPETENCY_FRAMEWORK  # noqa: E402

_CHAPTERS = [k for k in COMPETENCY_FRAMEWORK.keys() if k != "supplementary"]
_METAPHORS = ["항해", "나침반", "무대", "여정", "등대", "씨앗", "불꽃", "무기"]


def _msgs():
    out = []
    for ck in _CHAPTERS:
        first = next(iter(COMPETENCY_FRAMEWORK[ck]["indicators"].values()))["name"]
        out.append(_open(chapter=ck, user_definition="",
                         first_subcompetency_name=first, bridge_context=None))
    return out


def test_all_chapters_distinct_frames():
    msgs = _msgs()
    assert len(set(msgs)) == len(msgs), "챕터 간 앵커 틀이 반복됨"


def test_deterministic():
    """같은 입력 → 같은 출력(결정론)."""
    assert _msgs() == _msgs()


def test_no_metaphor():
    joined = " ".join(_msgs())
    for m in _METAPHORS:
        assert m not in joined, f"은유 '{m}' 사용됨"


def test_has_timeframe():
    for s in _msgs():
        assert "최근" in s or "근래" in s or "요즘" in s, s


def test_pool_size_covers_chapters():
    """프레임 풀이 챕터 수 이상이어야 무반복 보장."""
    assert len(_ANCHOR_FRAMES) >= len(_CHAPTERS)


def test_sub_name_not_exposed():
    """#2: 앵커 질문에 하위역량 '이름'이 노출되지 않는다(타겟은 백엔드만 안다).

    과거 테스트는 '이름 주입'을 요구했으나, 이름을 들은 대상자가 '그게 뭔지
    어렵다'고 되묻는 것이 로그로 확인돼 반전했다. 본문은 대화체 질문이 맡는다.
    """
    from diag_project.data.competencies import get_anchor_questions
    for ck in _CHAPTERS:
        key, ind = next(iter(COMPETENCY_FRAMEWORK[ck]["indicators"].items()))
        msg = _open(chapter=ck, user_definition="",
                    first_subcompetency_name=ind["name"], bridge_context=None)
        assert ind["name"] not in msg, (ck, ind["name"], msg)
        assert f"'{ind['name']}'" not in msg
        # 본문은 그 하위역량의 확정 질문 중 하나 그대로
        assert any(q in msg for q in get_anchor_questions(key)), (ck, msg)
        # 이중 질문 금지: 물음표는 하나
        assert msg.count("?") == 1, msg


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn(); print(f"  [PASS] {fn.__name__}")
    print("=== anchor pool: PASS ===")
