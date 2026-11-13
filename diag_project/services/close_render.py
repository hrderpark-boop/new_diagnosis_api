"""(2026-11-05 P4-6) 챕터 종료 요약 렌더 — 들은 사례 전부(2~3개)를 사례마다 한 문장씩, 리더 인용을 재료로 LLM 이 코치 문장으로 쓴다.

본 코치 호출(CHAPTER_READY_TO_END)은 직전 리더 답('네, 맞아요')에 끌려 질문을 이어 쓰는 일이 잦다(p4a Michael: 세 번 다 질문).
여기서는 대화 이력 없이 재료만 주는 집중 호출(Haiku)로 요약을 만들고, 사례별 겹침 검사(episodes_matched)를 통과한 것만 쓴다.
순수 검사 함수는 LLM 없이 테스트한다.
"""
from __future__ import annotations

import logging
import re

from diag_project.services.conjugation import JONG_L, JONG_SS, bad_form, jong_of
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


_HON_SUBJECT_RE = re.compile(r"([가-힣A-Za-z]{1,6})\s?님(?:은|는|이|가|께서|께서는)(?=\s)")


def _has_other_subject(sentence: str) -> bool:
    return any(not m.group(1).endswith("리더") for m in _HON_SUBJECT_RE.finditer(sentence or ""))


def drop_non_leader_subject(text: str | None) -> tuple[str, int]:
    """(P11e-4) 요약 문장의 주어 호칭이 '리더님'이 아닌 사람(대표님·○○ 님)이면 그 문장을 지운다. (결과, 지운 수) — 전부 걸리면 빈 문자열(호출자가 다시 쓰거나 요약 없이 간다)."""
    sents = [x.strip() for x in split_sentences(text or "") if x.strip()]
    kept = [x for x in sents if not _has_other_subject(x + " ")]
    if len(kept) == len(sents):
        return (text or ""), 0
    return " ".join(kept), len(sents) - len(kept)


# ── (2026-11-14 P12e) 절 단위 삭제 — 결과·인과 절, 다른 사람이 주어인 절 ─────────────────────────────────────────
#   검토자 지시: 요약은 리더가 직접 한 일(언제·무엇을 했다)만. 결과·인과로 시작하거나 이어지는 절, 다른 사람이 주어인 절은 '그 절만' 지운다.
#   프롬프트만으로는 P12b·c·d 세 번 모두 샜다("…들으셨고, 그 결과 ○○이 먼저 자원했어요") — 결정론 뒤처리로 절을 떼고 앞 절을 종결로 맺는다.
#
#   절 나누기(_split_clauses) — 어절 끝 꼴로만 본다(형태소 분석 없음).
#     ① 쉼표가 없어도 나눔: 'ㅆ 받침 + 고/으며/고요/는데'(…셨고·했고·였고·바꿨고·셨으며·짜셨는데), '…시고/…시며' — 뒤에서 종결로 맺을 수 있는 꼴과 같다.
#     ② 쉼표가 있을 때만 나눔: 그 밖의 연결어미(…면서, …서, …는데, …지만, …한 뒤, …한 후 등). 명사 나열 쉼표('표, 일정')는 나누지 않는다.
#   절 판정(_clause_reason)
#     (가) 절 머리(문장 첫 절은 '리더님은' 바로 뒤도 머리로 본다)가 '그 결과(로)·이후(에/로/부터)·그 이후·그 뒤(로/에)·그 후·(그) 덕분에' → marker_head.
#          '이후'는 머리에 있을 때만 본다 — '면담 이후 표를 정리하셨고'처럼 다른 낱말 뒤에 붙은 시간 부사는 리더 행동 절이다. '그 결과를'(목적어)은 표지가 아니다.
#          절 안 어디든 '끌어내/끌어냈…', '이어졌/이어지/이어져' → marker_in.
#     (나) '리더님' 주어가 없고 사람 + 이/가/은/는/도/께서 가 있으면 → other_subject. 사람 = ○○ 님 · ○○ 씨 · 직함/역할 · 두 분 류 · 본인 · people(재료에서 확인된 이름).
#          그 사람이 절의 주어인지(안긴 절의 주어가 아닌지)는 서술어의 높임으로 가린다 — 코치는 리더에게 높임을 쓴다.
#            · '님'이 붙은 사람(대표님이, ○○ 님은)            → 언제나 지운다(문장 단위 삭제 drop_non_leader_subject 와 같은 기준).
#            · 직함·이름·본인·두 사람(높임 표시 없음)          → 서술어가 높임꼴(…셨…·…십니다·…시고)이 아닐 때만 지운다.
#                                                               '구 반장이 올린 표를 직접 고치셨습니다'는 리더 행동 절(안긴 절의 주어)이라 남긴다.
#            · '분'·'께서'로 높인 사람(두 분이, ○ 선임께서)    → 서술어가 높임꼴이어도 지운다('두 분이 먼저 자원하셨습니다'). 단 그 사람 뒤에 안긴 꼴
#                                                               (…ㄹ 때, …수 있/없, …다고 보셨/판단하셨)이 있고 서술어가 높임꼴이면 남긴다('두 분이 떠날 수 있다고 보셨고').
#          사물 주어('지연이', '일정이', '만족도가')는 보지 않는다 — 표지 없는 사물 주어 절은 남는다.
#     (다) 지운 절 바로 뒤에 이어지는 절은 리더 행동(리더님 주어·높임 서술어)으로 돌아오기 전까지 같이 지운다 → follows ('그 결과 A했고, B도 줄었습니다'의 B).
#   지운 뒤
#     문장 첫 절이 걸리면 그 문장 전체를 지운다 — 단 뒤에 '리더님은 …'으로 새로 시작하는 절(절 머리가 리더님 주어)이 있으면 거기서부터는 남긴다.
#     마지막 절이 지워졌으면 남은 끝 절의 연결어미를 떼고 종결로 맺는다(…셨고 → …셨습니다./…셨어요.).
#     맺을 수 없는 꼴(…하신 뒤, …하면서)이면 그 문장은 손대지 않고 원문을 둔다(깨진 문장을 만들지 않는다) — unsafe 로 센다.
_SURNAMES = "김이박최정강조윤장임한오서신권황안송류유홍전고문양손배백허남심노하곽성차주우구민진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용"
_SURNAMES_SPACED = "김박최정강조윤장임오서신권황안송류유홍문손배백허심노하곽성차우민진엄채원천방변염추소석설마길위표명왕옥육맹탁"   # 띄어 쓴 한 글자 — '이·한·전·모·주·현'은 관형사와 꼴이 같아 뺀다
_SUBJ_PART = r"(?:께서는|께서|이|가|은|는|도)"
_SUBJ_END = r"(?=[\s,.!?…]|$)"
_TITLES_STRONG = ("본부장|선임|수석|과장|대리|(?<!주)차장|부장|팀장|실장|대표|상무|전무|반장|조장|주임|사원|매니저|담당자|실무자|강사|팀원|구성원|직원"
                  "|동료|후배|선배|상사")          # '주차장이' 는 사람이 아니다
_TITLES_WEAK = "책임|이사"          # '책임이 있다', '이사가 끝나고' — 이름이 붙었거나 '님'이 있을 때만 사람으로 본다
_GROUPS = r"(?:한|두|세|네|여러)\s?분|(?:한|두|세|네|몇|여러)\s?(?:사람|명)|(?:그|이|저)\s?분(?:들)?|그\s?(?:사람|친구)(?:들)?|본인"   # '몇 분이 걸렸다'(시간)는 뺀다
_LEADER_SUBJ_RE = re.compile(rf"(?:리더님{_SUBJ_PART}|리더께서는?){_SUBJ_END}")
_LEADER_TOPIC_HEAD_RE = re.compile(r"^(?:리더님(?:께서는|께서|은|는|이|도)|리더께서는?)[,，]?\s+")
_EMBED_RE = re.compile(r"수\s?(?:있|없)|(?:다고|라고|냐고|자고)\s+(?:보셨|보시|판단하|여기|생각하|들으셨|들으시|아셨|느끼|짚으)")
_CLAUSE_HEAD_RE = re.compile(r"^(?:그\s?결과(?:로)?|(?:그\s?)?이후(?:에는|로는|부터|에|로)?|그\s?(?:뒤|후)(?:에는|로는|부터|에|로)?|(?:그\s?)?덕분에)(?=[\s,，]|$)")
_CLAUSE_IN_RE = re.compile(r"끌어[내냈낸낼냄]|이어(?:졌|지|져)")
_OTHER_SUBJ_RES: tuple[re.Pattern, ...] = (
    re.compile(rf"(?P<who>[가-힣A-Za-z]{{1,6}})\s?님(?:들)?{_SUBJ_PART}{_SUBJ_END}"),                                    # ○○ 님 · 대표님 (리더님 제외)
    re.compile(rf"(?:(?<![가-힣])(?!마음씨)[{_SURNAMES}][가-힣]{{1,3}}씨|[가-힣A-Za-z]{{2,4}}\s씨){_SUBJ_PART}{_SUBJ_END}"),   # ○○ 씨 — '날씨가'·'솜씨가' 는 아님
    re.compile(rf"(?:{_TITLES_STRONG})(?:님|분들|들|분)?{_SUBJ_PART}{_SUBJ_END}"),                                       # 직함·역할(앞에 이름이 붙든 말든)
    re.compile(rf"(?:(?<![가-힣])(?:[{_SURNAMES}](?:[가-힣]{{2}})?(?:{_TITLES_WEAK})|[{_SURNAMES_SPACED}]\s(?:{_TITLES_WEAK}))"
               rf"|(?:{_TITLES_WEAK})\s?님){_SUBJ_PART}{_SUBJ_END}"),                                                      # 김책임은 · 박 이사가 · 책임님이 ('조직의 책임이' 는 아님)
    re.compile(rf"(?<![가-힣])(?:{_GROUPS})(?:(?:\s?모두)?{_SUBJ_PART}{_SUBJ_END}|\s?모두(?=\s))"),                      # 두 분이 · 그분은 · 두 사람 모두
)
_HON_PRED_RE = re.compile(r"(?:셨|십니|세요|시(?:고|며|면서)요?)[가-힣]*[,，.!?…]*$|신\s(?:뒤|후|다음)(?:에|에는)?[,，]*$")
_CONN_COMMA_RE = re.compile(r"(?:면서|서|는데|지만|더니|다가|도록|려고|으나|고|며|자|니)$|^(?:뒤|후|다음)(?:에|에는)?$")
# 재료(리더 발화)에서 사람 이름 뽑기 — 사람임이 꼴로 확인되는 것만: 성 + 직무가 붙은 호칭('○기획', '○운영', '○책임'), '○○ 님/씨' 앞 낱말.
#   성으로 시작하는 세 글자 일반 패턴은 쓰지 않는다('기준을', '고객사', '정확도' 가 이름으로 잡힌다).
_MAT_NAME_TAIL = r"(?=(?:이랑|에게|한테|께서|하고|이|가|은|는|도|과|와|을|를|의|께|랑|님|씨)?(?:[^가-힣]|$))"
_MAT_ROLE_NAME_RE = re.compile(rf"(?<![가-힣])([{_SURNAMES}](?:{_TITLES_WEAK}|기획|운영)){_MAT_NAME_TAIL}")
_MAT_HON_NAME_RE = re.compile(rf"(?<![가-힣])(?:([가-힣]{{2,4}})\s(?:님|씨)|([{_SURNAMES}][가-힣]{{2}})(?:님|씨)){_MAT_NAME_TAIL}")
_NOT_A_NAME_RE = re.compile(rf"^(?:리더|고객|선생|손|부모|여러|모든|{_TITLES_WEAK})$|(?:{_TITLES_STRONG})$")


def people_in_material(episodes: list[dict] | None) -> list[str]:
    """(P12e) 사례 재료(context/action/result — 리더가 한 말)에 나온 사람 이름. 요약에서 이 이름이 주어인 절을 지우는 데 쓴다.
    직함으로 끝나는 호칭('○ 반장')은 직함 규칙이 이미 잡으므로 넣지 않는다 — 여기서는 직함 없이 주어로 설 수 있는 이름만."""
    names: list[str] = []
    for e in episodes or []:
        for k in ("context", "action", "result"):
            t = e.get(k) or ""
            found = [m.group(1) for m in _MAT_ROLE_NAME_RE.finditer(t)] + [m.group(1) or m.group(2) for m in _MAT_HON_NAME_RE.finditer(t)]
            for nm in found:
                if nm and nm not in names and not _NOT_A_NAME_RE.search(nm):       # 직함 낱말뿐이거나 직함으로 끝나면 뺀다('대리', '구성원' 은 직함 규칙 몫)
                    names.append(nm)
    return names


def _people_subject_re(people: list[str] | None) -> re.Pattern | None:
    names = sorted({p.strip() for p in (people or []) if p and len(p.strip()) >= 2 and p.strip() != "리더"}, key=len, reverse=True)
    if not names:
        return None
    alt = "|".join(r"\s?".join(re.escape(x) for x in n.split()) for n in names)
    return re.compile(rf"(?<![가-힣A-Za-z])(?:{alt})(?:\s?(?:님|씨))?{_SUBJ_PART}{_SUBJ_END}")


def _last_word(clause: str) -> str:
    toks = (clause or "").split()
    return toks[-1] if toks else ""


def _honorific_predicate(clause: str) -> bool:
    """절의 서술어(끝 어절)가 높임꼴인가 — …셨고·…셨습니다·…십니다·…시고·…하신 뒤."""
    toks = (clause or "").split()
    return bool(toks) and bool(_HON_PRED_RE.search(" ".join(toks[-2:]) if len(toks) >= 2 and re.match(r"^(?:뒤|후|다음)", toks[-1]) else toks[-1]))


def _other_person_subjects(clause: str, people_re: re.Pattern | None = None) -> list[tuple[str, str]]:
    """절에 '리더님' 주어가 없을 때, 주어 자리에 있는 다른 사람마다 (높임 종류, 그 뒤 글). 종류: 'nim'(님) | 'hon'(분·께서) | 'plain'."""
    c = (clause or "") + " "
    if _LEADER_SUBJ_RE.search(c):
        return []
    out: list[tuple[str, str]] = []
    for rx in (*_OTHER_SUBJ_RES, people_re):
        if rx is None:
            continue
        for m in rx.finditer(c):
            if "who" in m.groupdict() and (m.group("who") or "").endswith("리더"):
                continue
            g = m.group(0)
            out.append(("nim" if "님" in g else "hon" if re.search(r"분|께서", g) else "plain", c[m.end():]))
    return out


def _embedded_after(rest: str) -> bool:
    """사람 뒤에 안긴 꼴이 있는가 — '…ㄹ 때', '…수 있/없', '…다고 보셨/판단하셨'. 그 사람은 안긴 절의 주어다."""
    if _EMBED_RE.search(rest or ""):
        return True
    toks = (rest or "").split()
    return any(i > 0 and re.match(r"^때(?:에는|는|도|에|마다|부터)?[,，]?$", t) and jong_of(toks[i - 1][-1]) == JONG_L for i, t in enumerate(toks))


def _clause_reason(clause: str, people_re: re.Pattern | None = None) -> str:
    """지울 절이면 사유('marker_head' | 'marker_in' | 'other_subject'), 아니면 ''."""
    c = (clause or "").strip()
    if _CLAUSE_HEAD_RE.match(_LEADER_TOPIC_HEAD_RE.sub("", c)):
        return "marker_head"
    if _CLAUSE_IN_RE.search(c):
        return "marker_in"
    who = _other_person_subjects(c, people_re)
    if who:
        hon_pred = _honorific_predicate(c)
        for kind, rest in who:
            if kind == "nim" or not hon_pred or (kind == "hon" and not _embedded_after(rest)):
                return "other_subject"
    return ""


def _close_stem(word: str, *, past: bool = True) -> str | None:
    """연결어미로 끝난 어절 → 종결어미를 붙일 수 있는 과거 어간('들으셨고' → '들으셨', '보여주시며' → '보여주셨'). 안전하게 못 만들면 None."""
    w = (word or "").rstrip(",，")
    for tail in ("고요", "는데", "으며", "고", "며"):
        if not w.endswith(tail) or len(w) <= len(tail):
            continue
        stem = w[: -len(tail)]
        if jong_of(stem[-1]) == JONG_SS:
            return None if tail == "며" else stem          # 'ㅆ 받침 + 며'는 없는 꼴 — 건드리지 않는다
        if stem[-1] == "시" and tail in ("고", "며", "고요") and len(stem) >= 2 and past:
            return stem[:-1] + "셨"                        # 높임 '시' + 고/며 — 문장 끝이 과거일 때만 과거로 맺는다
        return None
    return None


def _split_clauses(sentence: str) -> list[str]:
    """문장을 절 조각으로 나눈다. 구분 쉼표·공백은 앞 조각 끝에 그대로 둔다(이어 붙이면 원문)."""
    toks = re.findall(r"\S+\s*", sentence or "")
    out, cur = [], ""
    for i, tok in enumerate(toks):
        cur += tok
        if i == len(toks) - 1:
            break
        w = tok.strip()
        if _close_stem(w) is not None or (w.endswith((",", "，")) and _CONN_COMMA_RE.search(w.rstrip(",，"))):
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def _close_clause(clause: str, *, formal: bool, past: bool) -> str | None:
    body = (clause or "").rstrip()
    head, _, last = body.rpartition(" ")
    stem = _close_stem(last, past=past)
    if stem is None:
        return None
    return (head + " " if head else "") + stem + ("습니다." if formal else "어요.")


def drop_result_clauses_detail(text: str | None, *, formal: bool, people: list[str] | None = None) -> tuple[str, dict]:
    """(P12e) 요약에서 결과·인과 절과 다른 사람이 주어인 절만 지우고 남은 앞 절을 말투에 맞는 종결로 맺는다.
    (결과, {"clauses": 지운 절 수, "sentences": 문장째 지운 수, "unsafe": 어미를 못 맺어 원문을 둔 문장 수, "reasons": [사유…]}).
    전부 지워지면 빈 문자열 — 호출자는 요약 없이 고정 다리만 낸다."""
    info: dict = {"clauses": 0, "sentences": 0, "unsafe": 0, "reasons": []}
    sents = [x.strip() for x in split_sentences(text or "") if x.strip()]
    people_re = _people_subject_re(people)
    out: list[str] = []
    changed = False
    for s in sents:
        clauses = _split_clauses(s)
        flags: list[str] = []
        for c in clauses:
            r = _clause_reason(c, people_re)
            if not r and flags and flags[-1] and not (_LEADER_SUBJ_RE.search(c + " ") or _honorific_predicate(c)):
                r = "follows"                              # (다) 지운 절에 이어지는 절 — 리더 행동으로 돌아오기 전까지
            flags.append(r)
        hit = [r for r in flags if r]
        if not hit:
            out.append(s)
            continue
        if flags[0]:                                       # 첫 절이 걸리면 문장 전체 — 뒤에 '리더님은 …'으로 새로 시작하는 절이 있을 때만 거기서부터 남긴다
            k = next((i for i, r in enumerate(flags) if not r), None)
            if k is None or not _LEADER_TOPIC_HEAD_RE.match(clauses[k].lstrip()):
                info["clauses"] += len(clauses)
                info["sentences"] += 1
                info["reasons"] += hit
                changed = True
                continue
        kept = [c for c, r in zip(clauses, flags) if not r]
        if flags[-1]:                                      # 마지막 절이 지워졌다 — 남은 끝 절을 종결로 맺는다
            past = any(jong_of(ch) == JONG_SS for ch in _last_word(s))
            closed = _close_clause(kept[-1], formal=formal, past=past)
            kept[-1] = closed or ""
        new = "".join(kept).strip() if kept[-1] else ""
        if not new or (bad_form(new) and bad_form(new) != bad_form(s)):
            info["unsafe"] += 1                            # 맺을 수 없는 꼴 — 원문을 둔다
            out.append(s)
            continue
        info["clauses"] += len(hit)
        info["reasons"] += hit
        changed = True
        out.append(new)
    if not changed:
        return (text or ""), info
    return " ".join(out), info


def drop_result_clauses(text: str | None, *, formal: bool, people: list[str] | None = None) -> tuple[str, int]:
    """drop_result_clauses_detail 의 (결과, 지운 절 수) 꼴."""
    out, info = drop_result_clauses_detail(text, formal=formal, people=people)
    return out, int(info["clauses"])


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
    n_do = "두" if n_sum == 2 else "두세"
    # (P12e) 절 삭제에 쓸 말투와 사람 이름 — 합쇼체 코치(Jessica·Daniel·Lucas)는 '…셨습니다.', 나머지는 '…셨어요.' 로 맺는다
    from diag_project.services.intro_messages import line_register
    formal = line_register(persona_name) == "formal"
    people = people_in_material(eps)
    base = (
        f"당신은 리더십 BEI 코치 {persona_name or 'Ella'}입니다. 지금 영역에서 들은 이야기 {n}개를 리더에게 짧게 되짚는 문장을 씁니다.\n\n"
        f"[재료 — 리더가 한 말 그대로]\n{_material(eps)}\n\n"
        # (2026-11-14 P12e) 검토자 지시 — 요약은 리더가 직접 한 일(언제·무엇을 했다) 두세 가지만, 결과·인과는 쓰지 않는다.
        #   P12b~d 에서 넣었던 결과 허용 문구(행동 뒤에 수치·달라진 상태를 붙이는 문장 틀, 결과 표지 뒤에 올 수 있는 것 세 가지, 행동이 없으면 결과를 쓰라는 말,
        #   '~하셨고 …했습니다' 꼴 안내)는 뺐다 — 뒤 절 자리를 열어 두면 다른 사람이 한 일이 그 자리로 샜다(p12·p12b·p12c 세 번).
        #   금지할 낱말과 완성 문장은 프롬프트에 적지 않는다(적으면 그대로 베낀다) — 설명으로만 쓰고, 새는 절은 drop_result_clauses 가 뒤에서 지운다.
        f"[규칙]\n- 아래 이야기들을 합쳐 2~{n_sum}문장으로. 어떻게 썼는지 설명하지 말고 문장만 쓴다.\n"
        f"- 요약에는 리더가 직접 한 일 {n_do} 가지만 쓴다. 언제 무엇을 했는지를, 리더가 쓴 말을 살려 과거 사실로 쓴다(존댓말). 재료에 행동이 없는 이야기는 그때 상황만 쓴다.\n"
        "- 리더가 한 일에서 문장을 맺는다. 한 일의 다음 이야기(무엇이 어떻게 달라졌는지, 누가 무엇을 하게 되었는지)는 쓰지 않는다 — "
        "재료에 '결과'가 적혀 있어도 요약에는 옮기지 않는다. 결과나 까닭을 잇는 말로 문장을 늘이지 않는다.\n"
        "- 한 문장은 70자 안쪽으로 짧게. 따옴표 인용 나열이 아니라 코치의 문장으로. '사례 1에서는', '첫 사례에서는', '다음 사례에서는' 같은 번호·순서 매기기 금지.\n"
        "- 문장 첫머리 접속사('그래서', '그리고') 금지. 평가·칭찬('좋은', '인상적', '잘') 금지. 질문·예고·전환('이제 …로') 금지. 재료에 없는 사실 금지.\n"
        # (2026-11-12 P11e-4) '리더가 아닌 사람은 이름을 주어로' 규칙(P11d)은 되돌렸다 — 두 시뮬 모두에서 사람이 뒤바뀌었다(박선임 → 이기획, 리더 → 대표님).
        "- 다른 사람이 한 말·행동은 넣지 않는다. 문장의 주어는 언제나 '리더님'이다(다른 사람을 주어로 세우지 않는다). "
        "한 문장에 일을 둘 이어 쓸 때도 둘 다 리더가 한 일이다.\n"
        "- 리더가 말하지 않은 사실을 쓰지 않는다.\n"
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
        # (P12e) 절 단위 삭제를 먼저, 문장 단위 삭제(P11e-4)를 그 뒤에 — 순서를 바꾸면 '리더님은 A하셨고, ○○ 님은 B했습니다'가 문장째 지워져
        #   리더가 한 일(A)까지 잃는다. 절 삭제가 어미를 못 맺어 그대로 둔 문장에 ○○ 님 주어가 남아 있으면 뒤의 문장 단위 삭제가 받는다.
        cand, _cl = drop_result_clauses_detail(cand, formal=formal, people=people)
        cand, _n_subj = drop_non_leader_subject(cand)
        if _cl["clauses"] or _cl["unsafe"] or _n_subj:
            # 반환 꼴 (요약, 되짚은 사례 수)는 그대로 — 지운 수는 로그로 남긴다(로그 열쇠말 'close_summary_clause_drop')
            logger.info("close_summary_clause_drop round=%d clauses=%d sentences=%d unsafe=%d subject_sentences=%d reasons=%s",
                        i + 1, _cl["clauses"], _cl["sentences"], _cl["unsafe"], _n_subj, ",".join(_cl["reasons"]))
        m = episodes_matched(cand, eps) if cand else 0
        if n >= 2 and len([x for x in split_sentences(cand) if x.strip()]) < 2:
            m = min(m, need - 1)                       # (p9c) 한 문장짜리는 요건 미달로 — 다시 쓴다
        if m > best_n:
            best, best_n = cand, m
        if best_n >= need:
            break
        prompt = base + f"\n\n🚨 방금 출력은 재료 {n}개 중 {m}개만 되짚었습니다. 빠진 재료(행동)를 넣어 {n_sum}문장 안으로 다시 쓰세요."
    return best, best_n


# ── (2026-11-10 P9-9 → 2026-11-11 P10-5) 세션 마지막 답 받기 1문장 ─────────────────────────────────────────────
#   LLM 1문장, 리더 답의 낱말 인용 필수. 불합격이면 한 번 더 쓰고, 그래도 안 되면 리더 답의 마지막 절을 그대로 받는다(quote_receive).
#   어느 답에나 붙는 고정 문구('흥미로운 지점이에요')는 없다 — 받을 내용이 없으면('네'·'없어요') 받기 없이 종료 문구로 간다.
_LAST_RECV_MAX = 80


def last_receive_ok(sentence: str | None, user_text: str | None) -> tuple[bool, str]:
    """마지막 답 받기 형식 검사 — (통과, 사유). 평서문 1문장 · 리더 낱말 인용 · 질문·조언·가정·평가·상태 보고 없음 · 길이."""
    from diag_project.services.output_guard import close_side_violation, find_state_leak, is_question
    from diag_project.services.receive_check import receive_has_content
    cand = (sentence or "").strip()
    if not cand:
        return False, "empty"
    if is_question(cand) or close_side_violation(cand):
        return False, "question_or_advice"
    if find_praise(cand) or find_state_leak(cand):
        return False, "praise_or_state"
    if len(cand) > _LAST_RECV_MAX:
        return False, "length"
    if not receive_has_content(cand, user_text):
        return False, "no_quote"
    return True, ""


async def render_last_receive(llm, *, user_text: str | None, persona_name: str | None, rounds: int = 2) -> tuple[str, str]:
    """(받는 문장, 모드). 모드 'llm' | 'llm_regen' | 'quote'(리더 절 인용 폴백) | 'none'(받을 내용 없음)."""
    import os

    from diag_project.services.bei_engine import is_no_case_text
    from diag_project.services.receive_check import leader_nouns, quote_receive
    ut = re.sub(r"\s+", " ", (user_text or "").strip())
    if not ut or is_no_case_text(ut) or len(ut.replace(" ", "")) < 8 or not leader_nouns(ut):
        return "", "none"
    fallback = quote_receive(ut)
    if llm is None or os.getenv("FM_LLM_STUB"):
        return (fallback, "quote") if fallback else ("", "none")
    base = (
        f"당신은 리더십 BEI 코치 {persona_name or 'Ella'}입니다. 리더의 마지막 답을 받는 문장을 정확히 한 문장 씁니다.\n\n"
        f"[리더의 마지막 답]\n{ut[-400:]}\n\n"
        "[규칙]\n- 리더가 위에서 쓴 낱말(구절)을 그대로 넣어, 들은 사실만 다시 말하는 평서문 한 문장(존댓말, 60자 안쪽).\n"
        "- 어느 답에나 붙일 수 있는 말('그러셨군요', '잘 들었습니다')로 때우지 않는다.\n"
        "- 질문·평가·칭찬·조언·가정('~했다면')·감사·작별·진행 안내 금지. 리더가 하지 않은 말 금지.\n\n출력: 문장만."
    )
    prompt, mode = base, "llm"
    for attempt in range(max(1, rounds)):
        try:
            out = await llm._generate_with_retry(prompt=prompt, max_tokens=120, thinking_budget=0, call_type="last_receive", temperature=0.3)
        except Exception as e:  # noqa: BLE001
            logger.warning("마지막 답 받기 렌더링 실패: %s", e)
            break
        sents = [x.strip() for x in split_sentences(re.sub(r"\s*\n+\s*", " ", (out or "").strip().strip('"“”'))) if x.strip()]
        cand = sents[0] if sents else ""
        ok, why = last_receive_ok(cand, ut)
        if ok:
            return cand, mode          # 받는 문장은 어미를 강제하지 않는다
        mode = "llm_regen"
        prompt = base + f"\n\n🚨 방금 출력은 조건에 맞지 않았습니다({why}). 리더가 쓴 낱말을 넣은 평서문 한 문장으로 다시 쓰세요."
    return (fallback, "quote") if fallback else ("", "none")
