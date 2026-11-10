"""(2026-11-05 P4-6) 챕터 종료 요약 렌더 — 들은 사례 전부(2~3개)를 사례마다 한 문장씩, 리더 인용을 재료로 LLM 이 코치 문장으로 쓴다.

본 코치 호출(CHAPTER_READY_TO_END)은 직전 리더 답('네, 맞아요')에 끌려 질문을 이어 쓰는 일이 잦다(p4a Michael: 세 번 다 질문).
여기서는 대화 이력 없이 재료만 주는 집중 호출(Haiku)로 요약을 만들고, 사례별 겹침 검사(episodes_matched)를 통과한 것만 쓴다.
순수 검사 함수는 LLM 없이 테스트한다.
"""
from __future__ import annotations

import logging
import re

from diag_project.services.output_guard import (
    _content_chunks, drop_question_sentences, find_praise, split_sentences, strip_case_numbering, strip_leading_conjunction,
    strip_praise, strip_state_leak, strip_transition_sentences,
)

logger = logging.getLogger(__name__)

_NOTICE_RE = re.compile(r"(보세요|주세요|볼게요|보겠습니다|주십시오)[.!…]?$|되짚어|여쭙|여쭤|궁금")


def clean_close_summary(text: str, n_eps: int, *, no_case_tail: bool = False) -> str:
    """질문·칭찬·상태 누설·전환·예고 문장을 걷어내고 '사례 N에서는' 번호 매기기를 떼어 사례 수만큼(최소 2문장) 남긴다."""
    from diag_project.services.output_guard import drop_unfinished_tail
    from diag_project.services.output_guard import drop_summary_noise
    t, _ = drop_unfinished_tail(text or "")          # (P9, p9b) 토큰 상한에서 잘린 꼬리 문장은 버린다
    t, _ = drop_summary_noise(t)                     # (P9, p9c) 지시문 되읊기·해석 문장은 요약이 아니다
    t, _ = drop_question_sentences(t)
    t, _ = strip_praise(t)
    t, _ = strip_state_leak(t)
    t, _ = strip_transition_sentences(t)
    sents = [x for x in split_sentences(t) if x.strip() and not _NOTICE_RE.search(x)]
    if no_case_tail:
        sents = [x for x in sents if not re.search(r"(없(었|으|다|을|는)|떠오르|좁혀|방향을\s*(조금\s*)?바꿔|다른\s*(방향|쪽|질문)|여쭙|여쭤)", x)]
    sents = [strip_case_numbering(x).strip() for x in sents]
    return " ".join([x for x in sents if x][:min(3, max(2, n_eps))]).strip()   # (2026-11-10 P9-9) 사례와 보완 답을 합쳐 2~3문장


def episodes_matched(text: str, episodes: list[dict]) -> int:
    """재료(사례 인용 context/action/result)와 내용 어절 2개 이상 겹치는 사례 수 — 사례마다 한 문장이 실제로 그 사례를 되짚는지."""
    ct = set(_content_chunks(text or ""))
    n = 0
    for e in episodes or []:
        ec = {c for k in ("context", "action", "result") for c in _content_chunks(e.get(k) or "") if len(c) >= 2}
        if len(ec & ct) >= 2:
            n += 1
    return n


def _material(episodes: list[dict]) -> str:
    lines = []
    for e in episodes:
        parts = [f"{lab}: {strip_leading_conjunction(e.get(k))}" for k, lab in (("context", "상황"), ("action", "행동"), ("result", "결과")) if e.get(k)]
        if parts:
            lines.append("- " + " / ".join(parts))        # (p9c) '사례'·'보완 답' 꼬리표를 주면 그 말을 되읊는다 — 꼬리표 없이 내용만
    return "\n".join(lines)


async def render_close_summary(llm, *, episodes: list[dict], persona_name: str | None, register_hint: str = "", rounds: int = 2) -> tuple[str, int]:
    """(요약, 되짚은 사례 수). 집중 호출 최대 rounds 회 — 전부 되짚은 후보가 나오면 즉시, 아니면 가장 많이 되짚은 후보."""
    eps = [e for e in (episodes or []) if any(e.get(k) for k in ("context", "action", "result"))]
    if llm is None or not eps:
        return "", 0
    n = len(eps)
    n_sum = min(3, max(2, n))      # (2026-11-10 P9-9) 2~3문장
    need = min(n, 2)
    base = (
        f"당신은 리더십 BEI 코치 {persona_name or 'Ella'}입니다. 지금 영역에서 들은 이야기 {n}개를 리더에게 짧게 되짚는 문장을 씁니다.\n\n"
        f"[재료 — 리더가 한 말 그대로]\n{_material(eps)}\n\n"
        f"[규칙]\n- 아래 이야기들을 합쳐 2~{n_sum}문장으로. 어떻게 썼는지 설명하지 말고 문장만 쓴다. 각 문장은 행동(없으면 상황·결과)을 리더가 쓴 말을 살려 과거 사실로 쓴다('~하셨고 …했습니다' 꼴, 존댓말).\n"
        "- 한 문장은 70자 안쪽으로 짧게. 따옴표 인용 나열이 아니라 코치의 문장으로. '사례 1에서는', '첫 사례에서는', '다음 사례에서는' 같은 번호·순서 매기기 금지.\n"
        "- 문장 첫머리 접속사('그래서', '그리고') 금지. 평가·칭찬('좋은', '인상적', '잘') 금지. 질문·예고·전환('이제 …로') 금지. 재료에 없는 사실 금지.\n"
        + (f"- 말투: {register_hint}\n" if register_hint else "")
        + "\n출력: 문장만."
    )
    best, best_n = "", 0
    prompt = base
    for i in range(max(1, rounds)):
        try:
            out = await llm._generate_with_retry(prompt=prompt, max_tokens=480, thinking_budget=0, call_type="close_summary", temperature=0.4)
        except Exception as e:  # noqa: BLE001
            logger.warning("종료 요약 렌더링 실패: %s", e)
            break
        cand = clean_close_summary(re.sub(r"\s*\n+\s*", " ", (out or "").strip().strip('"“”')), n)
        if find_praise(cand):
            cand, _ = strip_praise(cand)
        m = episodes_matched(cand, eps) if cand else 0
        if n >= 2 and len([x for x in split_sentences(cand) if x.strip()]) < 2:
            m = min(m, need - 1)                       # (p9c) 한 문장짜리는 요건 미달로 — 다시 쓴다
        if m > best_n:
            best, best_n = cand, m
        if best_n >= need:
            break
        prompt = base + f"\n\n🚨 방금 출력은 재료 {n}개 중 {m}개만 되짚었습니다. 빠진 재료(행동)를 넣어 {n_sum}문장 안으로 다시 쓰세요."
    return best, best_n


# ── (2026-11-10 P9-9) 세션 마지막 답 받기 1문장 ─────────────────────────────────────────────────────────────
_LAST_RECV_MAX = 70


async def render_last_receive(llm, *, user_text: str | None, persona_name: str | None) -> str:
    """세션의 마지막 리더 답을 받는 평서문 1문장. 질문·평가·조언·가정·상태 보고 없이 들은 사실만. 실패·형식 불합격·스텁은 페르소나 마무리 어구."""
    import os

    from diag_project.services.bei_engine import is_no_case_text
    from diag_project.services.output_guard import close_side_violation, find_state_leak, is_question
    from diag_project.services.persona_voice import tails_for
    fallback = tails_for(persona_name)[0]
    ut = re.sub(r"\s+", " ", (user_text or "").strip())
    if llm is None or os.getenv("FM_LLM_STUB") or not ut or is_no_case_text(ut) or len(ut.replace(" ", "")) < 8:
        return fallback
    prompt = (
        f"당신은 리더십 BEI 코치 {persona_name or 'Ella'}입니다. 리더의 마지막 답을 받는 문장을 정확히 한 문장 씁니다.\n\n"
        f"[리더의 마지막 답]\n{ut[-400:]}\n\n"
        "[규칙]\n- 리더가 쓴 낱말 하나를 넣어 들은 사실만 다시 말하는 평서문 한 문장(존댓말).\n"
        "- 질문·평가·칭찬·조언·가정('~했다면')·감사·작별·진행 안내 금지. 리더가 하지 않은 말 금지.\n\n출력: 문장만."
    )
    try:
        out = await llm._generate_with_retry(prompt=prompt, max_tokens=120, thinking_budget=0, call_type="last_receive", temperature=0.3)
    except Exception as e:  # noqa: BLE001
        logger.warning("마지막 답 받기 렌더링 실패: %s", e)
        return fallback
    sents = [x.strip() for x in split_sentences(re.sub(r"\s*\n+\s*", " ", (out or "").strip().strip('"“”'))) if x.strip()]
    cand = sents[0] if sents else ""
    if (not cand or is_question(cand) or close_side_violation(cand) or find_praise(cand) or find_state_leak(cand) or len(cand) > _LAST_RECV_MAX):
        return fallback
    return cand          # (승인 조건 1) 받는 문장은 어미를 강제하지 않는다
