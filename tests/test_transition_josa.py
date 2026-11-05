"""#1 전환 멘트: 예고에서 끝나고(질문 없음) 챕터명 뒤 조사가 받침에 맞는다.

로그 재현: "이제 다음 역량인 '성과관리'에 대해 … 현실에서 '성과관리'을 챙긴다는
건 참 쉽지 않죠. … 포인트는 뭐예요?" — 전환 예고 뒤에 시스템이
build_chapter_thought_question 을 덧붙였고(조사 오류 포함), 정의 질문이 두 번
나가는 순서 어긋남을 만들었다.
"""
import inspect
import re

import pytest

from diag_project.services.korean import get_josa, with_josa
from diag_project.data.competencies import COMPETENCY_FRAMEWORK
from diag_project.prompts.phase3a import layer3_state as L3
from diag_project.routes import diagnoses as D
from diag_project.services import intro_messages as IM

CHAPTERS = [k for k in COMPETENCY_FRAMEWORK if k != "supplementary"]
_BAD_JOSA = re.compile(r"관리'?(을|은|이|과|으로)(?=[\s,.'?)])")


def test_get_josa_basic():
    assert get_josa("성과관리", "을/를") == "를"
    assert get_josa("성과관리", "은/는") == "는"
    assert get_josa("성과관리", "으로/로") == "로"
    assert get_josa("직원", "을/를") == "을"
    assert get_josa("서울", "으로/로") == "로"     # ㄹ받침 특례
    assert get_josa("사람", "으로/로") == "으로"
    assert get_josa("'성과관리'", "을/를") == "를"  # 따옴표 감싼 단어


def test_with_josa_quote():
    assert with_josa("성과관리", "을/를", quote=True) == "'성과관리'를"
    assert with_josa("전략적 사고", "이/가") == "전략적 사고가"


def test_thought_question_pool_removed():
    assert not hasattr(IM, "build_chapter_thought_question")
    src = inspect.getsource(D)
    assert "build_chapter_thought_question" not in src.replace("# ", "")\
        .split("(제거됨)")[0] or "build_chapter_thought_question(" not in src






