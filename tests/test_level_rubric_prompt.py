"""(2026-10-23, 2번) 레벨 기준 일원화 — 심층분석 프롬프트에 하위역량 루브릭 주입, STEP A 는 근거 충분성만.
캐시 키는 바뀌지 않아야 한다(420f1341 gemini 캐시 보존): 변경 전 산출한 키와 바이트 동일."""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project import llm_service as L  # noqa: E402
from diag_project.services.level_gate import GATE_PROMPT_VERSION, _persist_key  # noqa: E402

SUBS = ["비전 제시 및 공유", "전략적 사고", "변화관리(변화지향)", "혁신적 사고"]


def test_rubric_block_has_all_subs_and_levels():
    b = L._build_rubric_block("organization_management", SUBS)
    for s in SUBS:
        assert f"[{s}]" in b
    assert b.count("· Lv.3:") == 4 and "환경 변화 및 데이터를 근거로 전략을 수립" in b      # 전략적 사고 Lv.3 원문
    assert "시장, 고객, 경쟁 데이터를 수집" in b                                             # examples 도 포함
    assert L._build_rubric_block("organization_management", []) == "" and L._build_rubric_block("없는키", SUBS) == ""


def test_prompt_uses_rubric_not_step_a_for_levels():
    src = inspect.getsource(L.GeminiService._analyze_single_competency)
    assert "{_rubric_block}{_role_block}{_focus_block}" in src
    assert "STEP A — 근거 충분성" in src and "하위역량 level 결정에는 쓰지 않는다" in src
    assert "[하위역량 루브릭] 의 그 하위역량 Lv.1~4 서술·예시와 대조" in src
    assert "STEP A 루브릭(Lv1 증거 없음~Lv4 시스템화)을 그대로 적용" not in src


def test_cache_keys_unchanged_bytes():
    """변경 전(커밋 5cfed1c) 같은 입력으로 산출한 키. 프롬프트 버전·키 성분을 바꾸면 여기서 깨진다."""
    assert L._ANALYSIS_PROMPT_VERSION == "2026-08-20.v2-e2a" and GATE_PROMPT_VERSION == "2026-11-06.v3-episode"
    ks = L._deep_cache_keys("organization_management", "리더: 테스트 발언", "코치: 안녕\n리더: 테스트 발언",
                            {"전략적 사고", "비전 제시 및 공유"}, 1, provider="gemini")
    assert ks == ["32d6ed9afbc2fc0853093deac6cda2928baf89b738b4de117f9e85b34bb81fa7"]   # (2026-11-05 P4-8) 게이트 버전 성분이 바뀌어 새 키(이전 32d6ed9a…) — 의도된 무효화
    kc = L._deep_cache_keys("organization_management", "리더: 테스트 발언", "코치: 안녕\n리더: 테스트 발언",
                            {"전략적 사고", "비전 제시 및 공유"}, 1, provider="claude")
    # (2026-10-29 P2-4) claude 키는 _DEEP_PROMPT_VERSION_CLAUDE 성분이 더해져 바뀌었다(의도된 변경: 재배치된 프롬프트의 결과는 새 키). gemini 키는 그대로.
    assert kc == ["be10157b94f2134b6fca028fccb5525228ef3526d3a18641b0cc6661e0439dda"]   # (2026-11-05 P4-8) _DEEP_PROMPT_VERSION_CLAUDE v4-lv3design → 새 키(이전 48359f77…)
    assert _persist_key("organization_management", "전략적 사고", ["발화 A"], 3, "gemini") == \
        "3a4e3e77489be480c71c8a530301b99625105478770d7576ef790619a9f11b0c"   # (2026-11-05 P4-8) 게이트 규칙 6 → 새 키(이전 2c4b011d…)


def test_split_deep_prompt_is_text_preserving():
    """(2026-11-02 P2-4) 캐시 경계 분할은 프롬프트 텍스트를 바꾸지 않는다."""
    from diag_project.llm_service import _split_deep_prompt, _DEEP_SPLIT_LOG, _DEEP_SPLIT_ACC
    p = "머리\n역량 블록\n" + _DEEP_SPLIT_LOG + " (맥락)]\n로그 본문\n\n" + _DEEP_SPLIT_ACC + "\n꼬리"
    blocks, tail = _split_deep_prompt(p)
    assert len(blocks) == 2 and "".join(blocks) + tail == p and blocks[1].startswith(_DEEP_SPLIT_LOG) and tail.startswith(_DEEP_SPLIT_ACC)
    assert _split_deep_prompt("표식 없음") == (None, "표식 없음")
