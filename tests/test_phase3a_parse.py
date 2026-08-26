"""Q1: USE_PHASE3A 느슨한 파싱 고정 테스트 (조용한 레거시 누수 방지)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.config import phase3a_enabled  # noqa: E402


def test_truthy_variants():
    for v in ("true", "True", "TRUE", " true ", '"true"', "'true'", "1",
              "yes", "on", " ON "):
        os.environ["USE_PHASE3A"] = v
        assert phase3a_enabled() is True, v


def test_falsy_variants():
    for v in ("false", "False", "", "0", "no", "off", "  ", "maybe"):
        os.environ["USE_PHASE3A"] = v
        assert phase3a_enabled() is False, v


def test_unset_defaults_false():
    os.environ.pop("USE_PHASE3A", None)
    assert phase3a_enabled() is False


if __name__ == "__main__":
    for fn in (test_truthy_variants, test_falsy_variants,
               test_unset_defaults_false):
        fn(); print(f"  [PASS] {fn.__name__}")
    print("=== phase3a parse: PASS ===")
