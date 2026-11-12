"""(2026-11-10 P9-7 → 2026-11-11 P10-3) 입버릇 상한 — 같은 관용구가 세션·챕터에 되풀이되지 않게 결정론으로 바꾼다.

11/10 운영 Jessica 세션: 여는 문장마다 '…살펴보려고 합니다', 질문마다 '…말씀해 주시겠습니까?'.
11/11 운영 Olivia 세션: '…궁금해요', 여는 문장마다 '이번에는 ~쪽 이야기예요', '~은 팀마다, 사람마다 다릅니다' 류 채움 문장.
  살펴보려고 (합니다/해요)        세션 2회
  말씀해 주시겠습니까             챕터 2회
  궁금해요/궁금합니다             챕터 1회 — 넘으면 '…는지 들려주시겠어요?' 로(다른 질문이 뒤에 있으면 그 문장을 지운다)
  이번에는 ~ 쪽 이야기            세션 2회 — 넘으면 그 문장을 지운다(뒤의 질문은 남는다)
  ~마다 … 다릅니다(채움 문장)     금지 — 그 문장을 지운다
상한을 넘는 출력은 대체 표현으로 바꾸거나 지운다(재생성 없음). 대체 표현은 순번으로 돌려 한 표현이 새 입버릇이 되지 않게 한다.
"""
from __future__ import annotations

import re

from diag_project.services.output_guard import is_question, split_sentences

_SALPYEO_RE = re.compile(r"살펴보려(?:고)?(?=\s*(?:합니다|해요|하는데요|합니다만|고요|요))")
_SALPYEO_ALTS = ("들어보려고", "짚어보려고", "여쭤보려고")
_MALSSEUM_RE = re.compile(r"말씀해\s*주시겠습니까\?")
_GUNGGEUM_RE = re.compile(r"궁금(?:해요|합니다|하네요|한데요|해지네요|해집니다|했어요|했습니다|해서요)")
_GUNGGEUM_TAIL_RE = re.compile(r"((?:는|은|인|을|ㄹ|던|였는|었는|했는|셨는)지)(?:가|도|는|를)?\s*(?:더\s*|좀\s*|정말\s*|참\s*)?궁금(?P<end>해요|합니다|하네요|한데요|해지네요|해집니다)[.!…]*$")
_SIDE_STORY_RE = re.compile(r"이번(?:에는|엔|에)\s[^.?!]{1,40}?쪽\s*(?:이야기|얘기)")
# 채움 문장 — 어느 주제에나 붙는 일반론('~하는 방식은 팀마다, 사람마다 다릅니다', '리더마다 선이 달라요')
_FILLER_RE = re.compile(r"(?:팀|사람|리더|조직|회사|부서|상황|경우)(?:마다|에 따라|별로)[^.?!]{0,40}(?:다르|달라|다릅|제각각|차이가|같지 않)")

CAPS = {"salpyeo": ("session", 2), "malsseum": ("chapter", 2), "gunggeum": ("chapter", 1), "side_story": ("session", 2), "filler": ("ban", 0)}


def count_phrases(texts: list[str]) -> dict[str, int]:
    joined = "\n".join(t or "" for t in texts or [])
    return {"salpyeo": len(_SALPYEO_RE.findall(joined)), "malsseum": len(_MALSSEUM_RE.findall(joined)),
            "gunggeum": len(_GUNGGEUM_RE.findall(joined)), "side_story": len(_SIDE_STORY_RE.findall(joined)),
            "filler": len(_FILLER_RE.findall(joined))}


def is_filler_sentence(sentence: str | None) -> bool:
    s = (sentence or "").strip()
    return bool(s) and not s.endswith("?") and bool(_FILLER_RE.search(s))


def _rewrite_gunggeum(sentence: str, formal: bool) -> str | None:
    """'…했는지 궁금해요.' → '…했는지 들려주시겠어요?' — 문장 끝의 간접 질문 꼴만. 다른 꼴은 None."""
    m = _GUNGGEUM_TAIL_RE.search(sentence.strip())
    if not m:
        return None
    is_formal = formal or m.group("end") in ("합니다", "해집니다")
    return sentence.strip()[: m.start()] + m.group(1) + (" 들려주시겠습니까?" if is_formal else " 들려주시겠어요?")


def enforce_phrase_caps(text: str | None, *, session_texts: list[str], chapter_texts: list[str], formal: bool = False) -> tuple[str, dict[str, int]]:
    """이번 출력에서 상한을 넘는 관용구를 대체 표현으로 바꾸거나 그 문장을 지운다. (결과, {키: 고친 수})."""
    out = text or ""
    sess, chap = count_phrases(session_texts), count_phrases(chapter_texts)
    used = {"salpyeo": sess["salpyeo"], "malsseum": chap["malsseum"], "gunggeum": chap["gunggeum"], "side_story": sess["side_story"]}
    done = {"salpyeo": 0, "malsseum": 0, "gunggeum": 0, "side_story": 0, "filler": 0}
    picked: list[str] = []

    def _sub(key: str, alts: tuple[str, ...]):
        def _f(m):
            if used[key] < CAPS[key][1]:
                used[key] += 1
                return m.group(0)
            joined = "\n".join(chapter_texts or [])
            counts = [joined.count(a) + sum(1 for x in picked if x == a) for a in alts]
            rep = alts[counts.index(min(counts))]            # 이 영역에서 가장 덜 쓴 대체 표현(같으면 앞의 것)
            picked.append(rep)
            done[key] += 1
            return rep
        return _f

    out = _SALPYEO_RE.sub(_sub("salpyeo", _SALPYEO_ALTS), out)
    # (2026-11-12 P11c-5) '말씀해 주시겠습니까?' 는 상한을 넘어도 바꾸지 않는다(원문 유지) — 대체 표현으로 바꾸자 같은 대체 표현('짚어 주십시오.')이
    #   한 영역에 7번 나왔고, 그 표현을 질문으로 읽지 못해 뒤 단계가 어긋났다. 지우면 질문이 끊기므로 지우지도 않는다. 횟수는 계속 센다(린트).

    # 문장 단위 — 줄 구조(목록·문단)는 그대로 두고 줄 안의 문장만 다룬다
    lines_out: list[str] = []
    all_sents = [x.strip() for ln in out.split("\n") for x in split_sentences(ln) if x.strip()]
    n_total = len(all_sents)
    seen = 0
    for line in out.split("\n"):
        sents = [x.strip() for x in split_sentences(line) if x.strip()]
        if not sents:
            lines_out.append(line)
            continue
        kept: list[str] = []
        for s in sents:
            seen += 1
            later_q = any(is_question(x) for x in all_sents[seen:])
            if is_filler_sentence(s) and n_total > 1:
                done["filler"] += 1
                continue
            if _SIDE_STORY_RE.search(s):
                if used["side_story"] < CAPS["side_story"][1]:
                    used["side_story"] += 1
                elif n_total > 1 and not s.endswith("?"):
                    done["side_story"] += 1
                    continue
            if _GUNGGEUM_RE.search(s):
                if used["gunggeum"] < CAPS["gunggeum"][1]:
                    used["gunggeum"] += 1
                elif later_q and n_total > 1:
                    done["gunggeum"] += 1            # 뒤에 진짜 질문이 있다 — 이 문장은 지운다(한 턴에 묻는 것은 하나)
                    continue
                else:
                    new = _rewrite_gunggeum(s, formal)
                    if new:
                        done["gunggeum"] += 1
                        s = new
            kept.append(s)
        if kept:
            lines_out.append(" ".join(kept))
    out2 = "\n".join(lines_out).strip()
    if any(done[k] for k in ("gunggeum", "side_story", "filler")) and out2:
        out = out2
    return out, {k: v for k, v in done.items() if v}
