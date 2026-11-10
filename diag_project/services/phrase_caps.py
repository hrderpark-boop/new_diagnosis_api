"""(2026-11-10 P9-7) 입버릇 상한 — 같은 관용구가 세션·챕터에 되풀이되지 않게 결정론으로 바꾼다.

11/10 운영 Jessica 세션: 여는 문장마다 '…살펴보려고 합니다', 질문마다 '…말씀해 주시겠습니까?'.
  살펴보려고 (합니다/해요)   세션 2회 상한
  말씀해 주시겠습니까        챕터 2회 상한
상한을 넘는 출력은 대체 표현으로 바꾼다(재생성 없음). 대체 표현은 순번으로 돌려 한 표현이 새 입버릇이 되지 않게 한다.
"""
from __future__ import annotations

import re

_SALPYEO_RE = re.compile(r"살펴보려(?:고)?(?=\s*(?:합니다|해요|하는데요|합니다만|고요|요))")
_SALPYEO_ALTS = ("들어보려고", "짚어보려고", "여쭤보려고")
_MALSSEUM_RE = re.compile(r"말씀해\s*주시겠습니까\?")
_MALSSEUM_ALTS = ("말씀해 주십시오.", "들려주십시오.", "짚어 주십시오.")

CAPS = {"salpyeo": ("session", 2), "malsseum": ("chapter", 2)}


def count_phrases(texts: list[str]) -> dict[str, int]:
    joined = "\n".join(t or "" for t in texts or [])
    return {"salpyeo": len(_SALPYEO_RE.findall(joined)), "malsseum": len(_MALSSEUM_RE.findall(joined))}


def enforce_phrase_caps(text: str | None, *, session_texts: list[str], chapter_texts: list[str]) -> tuple[str, dict[str, int]]:
    """이번 출력에서 상한을 넘는 관용구를 대체 표현으로 바꾼다. (결과, {키: 바꾼 수})."""
    out = text or ""
    used = {"salpyeo": count_phrases(session_texts)["salpyeo"], "malsseum": count_phrases(chapter_texts)["malsseum"]}
    done = {"salpyeo": 0, "malsseum": 0}

    def _sub(key: str, alts: tuple[str, ...]):
        def _f(m):
            if used[key] < CAPS[key][1]:
                used[key] += 1
                return m.group(0)
            rep = alts[(used[key] + done[key]) % len(alts)]
            done[key] += 1
            return rep
        return _f

    out = _SALPYEO_RE.sub(_sub("salpyeo", _SALPYEO_ALTS), out)
    out = _MALSSEUM_RE.sub(_sub("malsseum", _MALSSEUM_ALTS), out)
    return out, {k: v for k, v in done.items() if v}
