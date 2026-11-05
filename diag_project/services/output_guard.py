"""코치 출력 후처리 가드 (2026-09-16, Daniel 재주행 검토 5건) — 순수 함수, LLM/DB 없음.

프롬프트 지시만으로는 지켜지지 않는 것들을 백엔드가 출력 단계에서 강제한다.
  1) ALIGN 이중 질문: 정의 제시가 질문으로 끝나면 그 문장을 지우고 템플릿 앵커를 붙인다.
  2) 전환 환각: 종료 권한이 없는 턴에서 "다음 챕터로 넘어가겠습니다" 류를 지운다.
  3) 앵커 턴 이름 노출·오타겟: 26개 하위역량 이름이 나오거나 이미 asked 된 하위역량의
     질문과 명사 어절이 겹치면 현재 타겟의 템플릿 앵커로 교체한다.
  4) 평가적 칭찬 금지(BEI 원칙 — 평가자가 원하는 신호를 주면 답을 포장한다): 6명 공통 금지
     목록. 포함 문장을 지운다. 인정은 사실 확인("그 결정을 내리셨군요")까지.
  5) 되받기 정리: 허용 턴 = [요약 한 줄] + [질문] / 금지 턴 = [대체 한 줄] + [질문]. 겹치지 않게.
호출 순서(diagnoses.py 8-i): 위반 감지 → 재생성 1회 → 남은 위반은 여기서 하드 교정.
"""
import re

from diag_project.services.style_tracker import (
    _BRIDGE_RE,
    _content_chunks, _first_sentence, echoes_user, is_recap_opening, starts_with_ne_recap,
)

# ── 문장 분리 ──
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def split_sentences(text: str) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    return [s for s in _SENT_SPLIT.split(t) if s.strip()]


def is_question(sentence: str) -> bool:
    s = (sentence or "").strip()
    # (2026-10-21) "~시겠어요" 제외 — "분주하시겠어요" 같은 추측 문장이 질문으로 잘려 나갔다. 추측은 추측 규칙(프롬프트)이 맡는다.
    # (2026-10-22 P1-3) 간접 질문도 질문: "…궁금해요/궁금합니다/들려주세요/떠올려 주세요/말씀해 주세요" 로 끝나는 문장.
    #   챕터 종료·전환 턴에서는 제거되고, 탐침 턴에서는 '한 턴 한 질문' 에 포함된다.
    # (2026-10-28 P0-5) "~는지요/~셨는지요" 도 질문 — 평서문으로 보여 리드 상한이 복합 질문의 앞 절을 잘랐다.
    return s.endswith("?") or bool(re.search(r"(까요|습니까|을까요|나요|시겠습니까|실까요|는지요|은지요|인지요)[.!?…]?$", s)) \
        or bool(_INDIRECT_Q_RE.search(s))


# (2026-10-28 P0-4) '떠올려 주시면 좋겠습니다'·'들려주시지요' 류 청유도 간접 질문 — 정의 턴에서 LLM 질문으로 남아 고정 정의 질문과 겹쳤다.
# (2026-11-04 P3-4 2차) Michael 요청형 '…됐는지도요.'(생략형 청유)도 질문.
_INDIRECT_Q_RE = re.compile(r"((는지|은지|인지)도요|궁금(해요|합니다|하네요|한데요|해지네요)|부탁(드려요|드립니다|합니다|해요)|들려주(세요|시죠|시지요|실래요)|떠올려\s*주세요|말씀해\s*주세요|얘기해\s*주세요|있으면요|"
                            r"말씀해\s*주시(면|겠)|들려주시(면|겠)|이야기해\s*주세요|알려주세요|"
                            r"(떠올려|들려|말씀해|이야기해|얘기해|알려|보여|설명해)\s*주시면\s*(좋겠|감사|됩니다|돼요)[가-힣]*|"
                            r"(떠올려|들려|말씀해|이야기해|얘기해|알려|보여|설명해)\s*주(시겠|십시오|실까요|시지요|시죠)[가-힣]*|"
                            r"(는지|은지|인지)(만|를|도)?\s*(구체적으로\s*|먼저\s*)?(여쭙니다|여쭙겠습니다|여쭤보겠습니다|여쭤봅니다|여쭤볼게요|여쭤볼게|물어볼게요|묻겠습니다|여쭙겠어요|확인하고\s*싶습니다|여쭙고\s*싶습니다|알고\s*싶습니다|듣고\s*싶습니다))[.!…]?$")


# ── 1) ALIGN: 꼬리 질문 제거 ──
def strip_trailing_question(text: str) -> tuple[str, int]:
    """마지막 문장(들)이 질문이면 지운다. 최소 한 문장은 남긴다. (결과, 지운 수)"""
    sents = split_sentences(text)
    removed = 0
    while len(sents) > 1 and is_question(sents[-1]):
        sents.pop()
        removed += 1
    if removed == 0:
        return text, 0
    # 원문의 문단 구조를 최대한 살린다: 지운 문장을 원문 끝에서 걷어낸다
    out = text.rstrip()
    for _ in range(removed):
        m = list(_SENT_SPLIT.finditer(out))
        if m:
            out = out[: m[-1].start()].rstrip()
        else:
            break
    return out, removed


# ── 2) 전환 환각 ──
_TRANSITION_RE = re.compile(
    r"(다음\s*(챕터|영역|단계|주제)(로|으로)?\s*(넘어|이어|가|이동)|넘어가겠습니다|넘어가 보겠습니다|"
    r"이어가겠습니다|이어가 보겠습니다|(영역|챕터)(을|를|은|는)?\s*(마무리|정리|마치)|"
    r"충분히 (들었|여쭤|나눴|이야기)|여기서 (마무리|정리|매듭)|다음 (영역|챕터)(에서|으로) (뵙|만나)|"
    # (2026-10-23, 4-2) LLM 이 쓰는 다리 변형 — 고정 다리와 중복되므로 전부 전환 문장으로 본다
    r"(이어|넘어)가\s*(볼게요|볼까요|보죠|봅시다|보겠습니다|겠습니다)|"
    r"다음은\s*['‘\"]?(조직관리|성과관리|사람관리|일관리|자기관리)|"
    r"['‘\"](조직관리|성과관리|사람관리|일관리|자기관리)['’\"]\s*(으로|로)\s*(이어|넘어|가|들어)|"
    r"(조직관리|성과관리|사람관리|일관리|자기관리)\s*(영역|챕터|이야기)?(으로|로)\s*(넘어|이어|들어가|옮겨))"
)

def strip_transition_sentences(text: str) -> tuple[str, int]:
    """전환 선언 문장을 지운다. 질문이 남지 않으면 원문 유지(호출자가 폴백 판단)."""
    sents = split_sentences(text)
    kept = [s for s in sents if not _TRANSITION_RE.search(s)]
    removed = len(sents) - len(kept)
    if removed == 0 or not kept:
        return text, 0
    return " ".join(kept), removed


# ── 3) 앵커 턴: 하위역량 이름 노출 · 오타겟 ──
def name_variants(names: list[str]) -> list[str]:
    """'변화관리(변화지향)' → ['변화관리(변화지향)', '변화관리', '변화지향'] 등 괄호 제거 변형."""
    out: list[str] = []
    for n in names or []:
        n = (n or "").strip()
        if not n:
            continue
        out.append(n)
        base = re.sub(r"\s*\([^)]*\)", "", n).strip()
        if base and base != n:
            out.append(base)
        for inner in re.findall(r"\(([^)]*)\)", n):
            inner = inner.strip()
            if len(inner) >= 2:
                out.append(inner)
    # 길이 긴 것부터(부분 문자열 중복 방지는 호출자가 any 로 보므로 순서만)
    return sorted(set(out), key=len, reverse=True)


def find_sub_names(text: str, names: list[str]) -> list[str]:
    """출력에 포함된 하위역량 이름(변형 포함). 2자 이하 변형은 오탐 방지로 제외."""
    t = text or ""
    return [v for v in name_variants(names) if len(v) >= 3 and v in t]


# ── 4) 평가적 칭찬 금지 (6명 공통) ──
BANNED_PRAISE = [
    "훌륭한", "훌륭하", "매우 인상 깊", "인상 깊", "인상적", "깊은 통찰", "통찰력", "참으로 의미 있",
    "의미 있는 성과", "깊이 다가옵니다", "깊이 다가오", "본질을 정확히 짚", "정확히 짚어주셨",
    "탁월", "뛰어난", "뛰어나", "감탄", "대단하", "대단한", "존경", "모범적", "귀감", "완벽하",
    "놀라운", "놀랍", "역량이 돋보", "돋보입니다", "돋보이", "리더십이 빛", "빛나는", "귀한 경험",
    "소중한 경험", "값진", "멋진", "멋지", "훌륭", "깊이 공감합니다", "전적으로 공감",
    # (2026-10-21) 챕터 종료 요약의 평가 어휘
    "엿볼 수 있었", "엿보였", "고민과 노력", "노력이 느껴", "진심이 느껴", "역량을 보여",
    # 2026-09-17 보강(마무리 총평에서 재발): 인상적·돋보·선명하게 그려지는 등 평가적 총평
    "돋보", "인상적", "선명하게 그려", "그려지는 듯", "기준이 선명", "면모", "리더십이 느껴", "역량이 느껴",
    "저력", "내공", "진정한 리더", "리더로서의 자질",
]
_PRAISE_RE = re.compile("|".join(re.escape(p) for p in sorted(set(BANNED_PRAISE), key=len, reverse=True)))


def find_praise(text: str) -> list[str]:
    return sorted(set(m.group(0) for m in _PRAISE_RE.finditer(text or "")))


def strip_praise(text: str) -> tuple[str, int]:
    """금지 표현이 든 문장을 지운다. 질문만 남거나 전부 지워지면 마지막 질문 문장은 보존."""
    sents = split_sentences(text)
    if not sents:
        return text, 0
    # (2026-10-29 P1 p13) 질문 문장은 지우지 않고 칭찬 구절만 걷어낸다 — Michael '…인상적이네요, 반발은 없었나요? 있었다면 …?' 에서 앞 질문이
    #   통째로 지워져 '있었다면 …' 이 홀로 남았다(잘림 1건).
    kept = [s for s in sents if not _PRAISE_RE.search(s) or is_question(s)]
    removed = len(sents) - len(kept)
    if removed == 0 and not any(_PRAISE_RE.search(s) for s in sents):
        return text, 0
    if not kept:
        # 전부 칭찬이면 질문 문장만이라도 칭찬 구절을 걷어내 남긴다
        qs = [s for s in sents if is_question(s)]
        base = qs[-1] if qs else sents[-1]
        base = _PRAISE_RE.sub("", base)
        base = re.sub(r"[ \t]{2,}", " ", base).strip(" ,")
        return base, removed
    # (2026-09-29) 문장을 제자리에서 지운다 — 다시 이어 붙이면 문단·목록 줄바꿈이 사라진다(ALIGN 서식 파손)
    out = text
    for x in sents:
        if _PRAISE_RE.search(x):
            if is_question(x):
                _cx = re.sub(r"[ \t]{2,}", " ", _PRAISE_RE.sub("", x)).strip(" ,")
                out = out.replace(x, _cx, 1)
            else:
                out = out.replace(x, "", 1)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, removed


# ── 4-b) (2026-10-16) 재방문·재회 인사 금지 — 같은 자리(sitting) 안의 모든 LLM 턴 ──
#   gemini 리플레이: 첫 세션 INTRO 턴에 "네, 다시 뵙게 되어서 저도 반갑습니다." 가 나왔다. 프롬프트 금지만으로는 새고,
#   가드 목록에 없어 guard_log 에도 남지 않았다. 자리가 바뀐 뒤 첫 턴(재개)은 호출자가 제외한다.
BANNED_REVISIT = [
    "다시 뵙게 되", "다시 뵙", "다시 만나 뵙", "다시 만나게 되", "다시 만나서", "다시 만나니", "또 뵙", "또 만나",
    "오랜만", "다시 찾아주", "다시 와 주", "다시 오신", "돌아오신 것을 환영", "재방문", "지난번에 이어", "지난 시간에 이어",
]
_REVISIT_RE = re.compile("|".join(re.escape(p) for p in sorted(set(BANNED_REVISIT), key=len, reverse=True)))


def find_revisit_greeting(text: str) -> list[str]:
    return sorted(set(m.group(0) for m in _REVISIT_RE.finditer(text or "")))


def strip_revisit_greeting(text: str) -> tuple[str, int]:
    """재방문 인사가 든 문장을 제자리에서 지운다. 전부 지워지면 마지막 질문(또는 마지막 문장)에서 구절만 걷어내 남긴다."""
    sents = split_sentences(text)
    if not sents:
        return text, 0
    hit = [s for s in sents if _REVISIT_RE.search(s)]
    if not hit:
        return text, 0
    if len(hit) == len(sents):
        qs = [s for s in sents if is_question(s)]
        base = qs[-1] if qs else sents[-1]
        base = _REVISIT_RE.sub("", base)
        base = re.sub(r"^(네|예|음|아),?\s*", "", base.strip())
        base = re.sub(r"[ \t]{2,}", " ", base).strip(" ,")
        return base, len(hit)
    out = text
    for x in hit:
        out = out.replace(x, "", 1)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, len(hit)


# ── 4-c) (2026-10-19) 라포 2·3턴 / INTRO: LLM 출력에서 '되받기 한 문장'만 취한다 ──
#   질문은 백엔드 고정 문장이 붙는다(기록=발화 결합과 같은 방식). LLM 이 질문을 써도 여기서 제거된다.
def receive_sentence(text: str, fallback: str = "그러셨군요.") -> str:
    """질문 문장을 버리고 첫 평서문 하나만 돌려준다. 남는 게 없으면 fallback."""
    for s in split_sentences((text or "").strip()):
        s = s.strip()
        if not s or is_question(s):
            continue
        return s
    return fallback


def _compact(text: str) -> str:
    return re.sub(r"[\s.,!?~'\"“”‘’…·]+", "", text or "")


_QUOTE_SPAN_RE = re.compile(r"['‘’\"“”]([^'‘’\"“”\n]{1,40})['‘’\"“”]")
_QUOTE_HANDLE_RE = re.compile(r"(\S+?)(이라|라)(는\s*말씀|고\s*하|\s*하)")


def echoes_user(receive: str, user_text: str | None, n: int = 4) -> bool:
    """(2026-10-19) 되받기 문장이 리더 발화의 연속 n자 이상(공백·문장부호 제외)을 그대로 담으면 True(반복).
    (2026-10-21) n 6 → 4. 되물음(질문 문장)과 인용 손잡이("'그럭저럭'이라 하시니", "~라는 말씀")는 반복으로 치지 않는다
    — 리더 발화에서 나온 되물음은 허용이기 때문. 평서문(되받기)만 검사한다."""
    stmts = [s for s in split_sentences(receive or "") if not is_question(s)]
    body = " ".join(stmts)
    body = _QUOTE_SPAN_RE.sub(" ", body)
    body = _QUOTE_HANDLE_RE.sub(" ", body)
    r, u = _compact(body), _compact(user_text or "")
    if len(u) < n or not r:
        return False
    # (2026-10-21, 2차) 명사구 단독 재사용('하반기 교육 일정', '그럭저럭')은 허용. 리더 문장의 명사구 + 서술부(동사·어미)가
    #   함께 그대로일 때만 반복 — 최장 공통 부분 문자열(n자 이상)에 서술부 표지가 들어 있어야 한다.
    best = ""
    for i in range(len(u)):
        for j in range(i + max(n, len(best) + 1), len(u) + 1):
            if u[i:j] in r:
                best = u[i:j]
            else:
                break
    return len(best) >= n and bool(_PREDICATE_RE.search(best))


_PREDICATE_RE = re.compile(r"(하고|해서|했|하는|하며|하면|이에|있어|있는|있었|없어|없는|지내|몰려|되고|되는|됐|이고|인데|니까|려고|면서|"
                           r"보내|지냈|했어|했지|하지|하네|거든|이라서|라서|어서|아서|구요|고요|네요|어요|아요|지요|죠|예요)")


def smalltalk_followup_ok(question: str) -> bool:
    """(2026-10-21) 스몰톡 되물음이 일·업무·역할·팀을 묻지 않는가(그건 다음 턴 담당)."""
    return not _WORK_Q_RE.search(question or "")


_WORK_Q_RE = re.compile(r"(업무|역할|담당|맡고|맡으|맡은|맡기|챙기|직무|직책|직급|프로젝트|일정|교육|조율|우선순위|회의|보고|고객|무슨 일|어떤 일|어떤 분야|일로|일은|일이|일에|팀(은|이|을|에|에서|원|장)|회사에서|부서|조직|직접)")   # (2026-11-05) s2a: '직접 챙기시나요, 팀에 맡기시나요' 가 통과했다


def replace_statements(text: str, replacement: str = "그러셨군요.") -> str:
    """평서문을 모두 replacement 하나로 바꾸고 되물음(마지막 질문)은 보존한다."""
    qs = [s for s in split_sentences(text or "") if is_question(s)]
    return f"{replacement} {qs[-1]}".strip() if qs else replacement


def receive_sentences(text: str, max_statements: int = 2, allow_question: bool = True,
                      fallback: str = "그러셨군요.") -> str:
    """(2026-10-21) 라포 스몰톡 턴: 평서문 최대 max_statements + 되물음 최대 1(마지막 질문)."""
    sents = [s.strip() for s in split_sentences((text or "").strip()) if s.strip()]
    stmts = [s for s in sents if not is_question(s)][:max_statements]
    qs = [s for s in sents if is_question(s)]
    out = list(stmts)
    if allow_question and qs:
        out.append(qs[-1])
    if not out:
        return fallback
    return " ".join(out)


_REQUEST_Q_RE = re.compile(r"(들려주세요|는지도요|얘기해\s*주세요|말씀해\s*주세요|말씀해\s*주십시오)[.!…]?$")


# (2026-11-05 2단계 판정 2) 한 문장 안의 두 질문: '~는지, 그리고 ~?' / '~는지, 또는 ~' / '~는지, (그때·어떤·무엇·언제·왜·어떻게·누구) ~?'
#   — '~는지, 숫자든 현장 변화든 말씀해 주시겠습니까?' 처럼 뒤에 의문사·접속사가 없으면 한 질문이다(s2c Jessica 재생성 6턴 공회전의 원인).
_COMPOUND_Q_RE = re.compile(r"(는지|은지|인지|을지|였는지|었는지|했는지)[,，]\s*(?=(그리고|또는|아니면|또\s|그때|어떤|무엇|언제|어디|왜\s|어떻게|누구|누가))"
                            r"|[,，]\s*그리고\s+(?=(그때|그 뒤|리더님|어떤|무엇|언제|어디|왜\s|어떻게|배우신|느끼신|누구))")
# '…과 이어서 여쭙니다.' 류는 질문이 아니라 다음 질문으로 가는 다리 — 질문 수에 넣지 않는다
_LEAD_IN_Q_RE = re.compile(r"(이어서|이어|대해|관련해|관해|연결해서|연결해)\s*(여쭙니다|여쭤보겠습니다|여쭤볼게요|묻겠습니다|질문드리겠습니다|질문드립니다|여쭙겠습니다)[.…]?$")


def count_question_markers(text: str) -> int:
    """질문 표지 수 = 질문 문장(간접 질문·요청형 포함) 수 + 한 문장 안의 복합 질문 절. 2 이상이면 '두 질문'."""
    n = 0
    for s_ in split_sentences(text or ""):
        s_ = s_.strip()
        if not s_ or _LEAD_IN_Q_RE.search(s_):
            continue
        if is_question(s_):
            n += 1 + len(_COMPOUND_Q_RE.findall(s_))
    return n


def split_compound_question(text: str) -> tuple[str, int]:
    """두 질문이 한 문장에 든 질문 문장에서 앞 절('~는지, 그리고 ')을 떼고 뒤 질문만 남긴다. (결과, 고친 문장 수)"""
    out, n = [], 0
    for s_ in split_sentences(text or ""):
        s0 = s_.strip()
        if s0 and is_question(s0) and _COMPOUND_Q_RE.search(s0):
            parts = re.split(r"(?:는지|은지|인지|을지|였는지|었는지|했는지)[,，]\s*(?:그리고|또는|아니면|또)?\s*", s0)
            if len(parts) >= 2 and parts[-1].strip():      # '설득하셨는지, 속도를 조절하셨는지, 아니면 ~?' → 마지막 절만
                s0 = parts[-1].strip()
                n += 1
        out.append(s0)
    return " ".join(x for x in out if x), n


def count_questions(text: str) -> int:
    """(2026-11-04 P3-4 2차) 질문 수 = 물음표 수 + 물음표 없는 Michael 요청형 문장('…하나만 들려주세요.' / '…됐는지도요.').
    ALIGN 안내문('떠올려 주시면 됩니다')처럼 is_question 이 간접 질문으로 보는 고정 문장은 세지 않는다 — 앵커·ALIGN '질문 1개' 판정용."""
    t = text or ""
    return t.count("?") + t.count("？") + sum(1 for s in split_sentences(t) if "?" not in s and _REQUEST_Q_RE.search(s.strip()))


# (2026-11-04 P3 3차) 서술어 없이 끝난 문장 — 칭찬 구절 제거가 서술어를 지운 흔적('…보셨다는 점이 이에요.'). 조사로 끝나거나 계사 어절만 남은 문장.
_COPULA_ALONE = {"이에요", "예요", "이네요", "입니다", "이죠", "이군요", "이시네요", "이었어요", "이었습니다", "이고요", "이라서요", "인데요", "이에요.", "입니다."}
_PARTICLE_END_RE = re.compile(r"[가-힣]+(이|가|은|는|을|를|의|에|에서|에게|으로|로|과|와|도|까지|부터)$")
_SUGGESTION_RE = re.compile(r"((주|보|하|해\s*보|떠올려\s*보|생각해\s*보)셔도\s*(좋아요|좋습니다|괜찮아요|괜찮습니다|돼요|됩니다|좋겠어요|좋겠습니다)|"
                            r"(떠올려|생각해|돌아봐|짚어)\s*보(세요|셔요|시죠|시지요)|주셔도\s*(좋|괜찮)[가-힣]*)[.!…]?$")


def is_broken_sentence(sentence: str) -> bool:
    s = (sentence or "").strip()
    if not s or is_question(s):
        return False
    toks = s.rstrip(".!…").split()
    if not toks:
        return False
    last = toks[-1]
    if last in _COPULA_ALONE:
        return True
    return bool(_PARTICLE_END_RE.fullmatch(last)) and not re.search(r"(다|요|죠|네|까|오|게|지|며|고)$", last)


def broken_statements(text: str) -> list[str]:
    return [s for s in split_sentences(text or "") if is_broken_sentence(s)]


def replace_broken_statements(text: str, new_text: str | None) -> str:
    """깨진 평서문을 new_text 의 멀쩡한 평서문으로 하나씩 바꾼다(없으면 삭제). 질문·고정 문장은 그대로."""
    pool = [s.strip() for s in split_sentences(new_text or "") if s.strip() and not is_question(s) and not is_broken_sentence(s)]
    out = text or ""
    for b in broken_statements(out):
        out = out.replace(b, pool.pop(0) if pool else "", 1)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def strip_suggestion_statements(text: str) -> tuple[str, int]:
    """(2026-11-04 P3 3차) 되받기 뒤에 붙는 LLM 권유 평서문('…장면을 떠올려 주셔도 좋아요.')을 지운다. 질문은 그대로. (결과, 지운 수)"""
    sents = split_sentences(text or "")
    bad = [s for s in sents if not is_question(s) and _SUGGESTION_RE.search(s.strip())]
    if not bad:
        return text, 0
    out = text
    for b in bad:
        out = out.replace(b, "", 1)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip(), len(bad)


def keep_last_question(text: str) -> tuple[str, int]:
    """(2026-10-21) 한 턴 한 질문: 물음표 문장이 2개 이상이면 마지막 하나만 남긴다(평서문은 유지)."""
    sents = split_sentences(text or "")
    qs = [s for s in sents if is_question(s)]
    if len(qs) < 2:
        return text, 0
    # (2026-10-22) "A? 아니면 B?" 양자택일 쌍은 한 질문 — 마지막이 '아니면'으로 시작하면 바로 앞 질문도 남긴다
    # (2026-10-28 P0-5) "…있었나요? 있었다면 언제였고…?" 처럼 마지막 질문이 조건절로 시작하면 앞 질문이 주절 — 함께 남긴다
    keep = qs[-2:] if (qs[-1].lstrip().startswith(("아니면", "혹은", "또는")) or starts_without_main_clause(qs[-1])) else qs[-1:]
    if len(keep) == len(qs):
        return text, 0
    out = text
    for q in qs:
        if q in keep:
            continue
        out = out.replace(q, "", 1)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, len(qs) - len(keep)


_MOMENT_Q_RE = re.compile(r"순간(이|은|도|들이|들도)\s*(있었|있으셨|있었던|있으셨던|없었|없으셨)(을까요|나요|어요|습니까)\s*\?")


def fix_moment_question(text: str) -> tuple[str, int]:
    """(2026-10-21) 시점 질문 문형: '…순간이 있었을까요?' 금지 → '…장면은 언제였을까요?'."""
    new, n = _MOMENT_Q_RE.subn("장면은 언제였을까요?", text or "")
    return new, n


def foreign_quotes(text: str, user_text: str | None, exempt: list[str] | None = None) -> list[str]:
    """(2026-10-21) 출력의 '…' 인용구 중 리더 발화(user_text)에 없는 것. 역량·챕터 이름 등 exempt 는 제외."""
    u = _compact(user_text or "")
    ex = {_compact(e) for e in (exempt or []) if e}
    out = []
    for m in _QUOTE_SPAN_RE.finditer(text or ""):
        span = m.group(1).strip()
        c = _compact(span)
        if not c or c in ex or any(c in e or e in c for e in ex if len(e) >= 2):
            continue
        if not _quote_from_user(c, u):
            out.append(span)
    return out


def _quote_from_user(c: str, u: str) -> bool:
    """인용구(압축)가 리더 발화(압축)에서 왔는가. 어미 차이('…하는 것' vs '…하는 거요', '…한다' vs '…하니까요')는 허용:
    끝 1~3자를 뗀 접두가 발화에 있거나, 발화와의 최장 공통 부분 문자열이 인용구의 60% 이상이면 리더 말로 본다."""
    if not c or not u:
        return False
    if c in u:
        return True
    if len(c) < 4:
        return False
    for k in (1, 2, 3):
        if len(c) - k >= 4 and c[:-k] in u:
            return True
    best = 0
    for i in range(len(c)):
        for j in range(i + best + 1, len(c) + 1):
            if c[i:j] in u:
                best = j - i
            else:
                break
    return best >= max(4, int(len(c) * 0.6))


def strip_quote_marks(text: str, spans: list[str]) -> str:
    """해당 인용구의 따옴표만 뗀다(본문은 유지)."""
    out = text or ""
    for sp in spans:
        out = re.sub(r"['‘’\"“”]" + re.escape(sp) + r"['‘’\"“”]", sp, out)
    return out


# ── (2026-10-21) 상태 누설 문구 — 백엔드 상태('새 사례 확보', '충분히 들었다')를 리더에게 말하는 문장 ──
BANNED_STATE_LEAK = [
    "새로운 사례를 들려주", "새 사례를 들려주", "새로운 경험을 들려주", "새로운 사건", "사례를 하나 더 확보",
    "사례가 확보", "사례를 확보", "충분히 들었습니다", "충분히 여쭤", "여기까지 충분히", "사례가 수집", "데이터가 수집",
    "사례로 기록", "하나의 사례로", "또 다른 사례를 들려주", "새로운 사례",
    # (2026-10-22) 챕터 종료 요약의 집계 누설
    "사례는 두 가지", "사례는 세 가지", "사례는 네 가지", "사례는 다섯 가지", "사례는 한 가지", "말씀해 주신 사례는",
    # (2026-10-23 6번 보정) 집계·완료 누설 — "사건 두 개가 모두 정리되었습니다"(Jessica 재생 12턴)
    "정리되었습니다", "정리됐습니다", "정리가 되었습니다", "수집되었습니다", "수집됐습니다", "기록되었습니다", "확보되었습니다", "확보됐습니다",
    "사실 확인부터 해보겠습니다",
]
_STATE_LEAK_RE = re.compile(
    "|".join(re.escape(p) for p in sorted(set(BANNED_STATE_LEAK), key=len, reverse=True))
    + r"|사건\s*(한|두|세|네|다섯|\d+)\s*개|사례\s*(한|두|세|네|다섯|\d+)\s*(개|건)(가|이|를|을|는|은)?"
)


_META_ECHO_RE = re.compile(r"(답변\s*문장만|이렇게\s*됩니다|다시\s*쓰면|재생성|출력\s*규칙|지시문|시스템\s*지시)")


def strip_meta_echo(text: str) -> tuple[str, int]:
    """(2026-11-05 s2b) LLM 이 출력 규칙을 되읊은 문장('답변 문장만 드리면 이렇게 됩니다.')을 지우고, 남은 본문 전체가 따옴표로 감싸져 있으면 벗긴다."""
    sents = [x for x in split_sentences(text or "") if x.strip()]
    kept = [x for x in sents if not _META_ECHO_RE.search(x)]
    n = len(sents) - len(kept)
    out = " ".join(kept).strip()
    if len(out) >= 2 and out[0] in "\"“'‘" and out[-1] in "\"”'’":
        out = out[1:-1].strip()
        n += 1
    return out, n


def find_state_leak(text: str) -> list[str]:
    return sorted(set(m.group(0) for m in _STATE_LEAK_RE.finditer(text or "")))


def strip_state_leak(text: str) -> tuple[str, int]:
    """누설 문장을 제자리에서 지운다. 전부 지워지면 마지막 질문(또는 마지막 문장)에서 구절만 걷어낸다."""
    sents = split_sentences(text)
    if not sents:
        return text, 0
    hit = [s for s in sents if _STATE_LEAK_RE.search(s)]
    if not hit:
        return text, 0
    if len(hit) == len(sents):
        qs = [s for s in sents if is_question(s)]
        base = qs[-1] if qs else sents[-1]
        base = _STATE_LEAK_RE.sub("", base)
        base = re.sub(r"[ \t]{2,}", " ", base).strip(" ,")
        return base, len(hit)
    out = text
    for x in hit:
        out = out.replace(x, "", 1)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, len(hit)


# ── 4-c3) (2026-10-22 P2-3) 페르소나별 되받기 상한 · 관찰 문장 ──
PERSONA_LEAD_CAP = {"Ella": 2, "Daniel": 2, "Jessica": 1, "Lucas": 1, "Olivia": 2, "Michael": 2}
_OBS_PARTICLE_RE = re.compile(r"(으로|에서|에게|께서|이라|라고|이라고|과|와|은|는|이|가|을|를|의|에|도|로|만|까지|부터|처럼|보다|랑|이랑)$")
_OBS_STOP = {"리더님", "리더", "사이", "쪽", "것", "거", "때", "경우", "부분", "이야기", "말씀", "생각", "장면", "순간", "분", "번", "점"}


def persona_lead_cap(persona_name: str | None) -> int:
    key = (persona_name or "").split(" ")[0]
    return PERSONA_LEAD_CAP.get(key, 2)


def _sentence_nouns(sentence: str) -> list[str]:
    out = []
    for w in re.sub(r"[.!?…,\"'“”‘’()]", " ", sentence or "").split():
        w0 = re.sub(r"[^가-힣a-zA-Z0-9]", "", w)
        if re.search(r"(하는|되는|한|된|할|될|하셨|셨|였|있|없|했|던|시|겠|죠|요|네|다|지|고|서|면|며|워|운|웠)$", w0):
            continue   # 동사·형용사 활용형(원형 기준)
        w1 = _OBS_PARTICLE_RE.sub("", w0)
        if len(w1) >= 2 and w1 not in _OBS_STOP:
            out.append(w1)
    return out


def is_observation(sentence: str, user_text: str | None) -> bool:
    """(2026-10-22 P2-3) 관찰 문장: 리더 발화에 있는 사실·대비를 재구성한 문장 — 문장의 명사가 전부 리더 발화에서 왔는가.
    ('속도를 원하는 선임과 준비를 택한 리더님 사이였군요' 는 추측이 아니라 관찰)."""
    nouns = _sentence_nouns(sentence)
    if not nouns:
        return False
    u = _compact(user_text or "")
    return all(_compact(n) in u for n in nouns)


def cap_leads_persona(text: str, cap: int, user_text: str | None) -> tuple[str, int]:
    """질문 앞 평서문(되받기)을 페르소나 상한까지만 남긴다 — 관찰 문장을 먼저 남기고, 나머지는 앞에서부터."""
    sents = split_sentences(text or "")
    leads = [s for s in sents if not is_question(s)]
    if len(leads) <= cap:
        return text, 0
    keep = [s for s in leads if is_observation(s, user_text)][:cap]
    for s in leads:
        if len(keep) >= cap:
            break
        if s not in keep:
            keep.append(s)
    out = text
    for s in leads:
        if s not in keep:
            out = out.replace(s, "", 1)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, len(leads) - len(keep)


def strip_align_tail_statements(text: str) -> tuple[str, int]:
    """(2026-10-22 P2-3) ALIGN: 마지막 '· ' 목록 줄 뒤의 평서문(LLM 다리)을 지운다 — 다리는 시스템이 붙인다."""
    lines = (text or "").rstrip().split("\n")
    last_list = max((i for i, l in enumerate(lines) if l.strip().startswith("·")), default=None)
    if last_list is None:
        return text, 0
    head = "\n".join(lines[: last_list + 1])
    tail = "\n".join(lines[last_list + 1:])
    sents = [s for s in split_sentences(tail) if s.strip()]
    kept = [s for s in sents if is_question(s)]
    removed = len(sents) - len(kept)
    if removed == 0:
        return text, 0
    out = head + ("\n\n" + " ".join(kept) if kept else "")
    return out.strip(), removed


# ── 4-d) (2026-10-22 P2-1) 입버릇 반복 가드 — 되받기(평서문) 마무리 어구(마지막 어절 2개)를 세션 단위로 센다 ──
BANNED_TAILS = [
    "마음에 남아요", "마음에 남네요", "마음에 남습니다", "짐작이 되네요", "짐작이 됩니다", "짐작이 돼요",
    "인상에 남네요", "인상에 남아요", "인상에 남습니다", "그려지네요", "그려집니다", "그려져요",
    "분명하게 들어왔어요", "분명하게 들어왔습니다", "분명히 들어왔어요",
]
_BANNED_TAIL_RE = re.compile("|".join(re.escape(p) for p in sorted(set(BANNED_TAILS), key=len, reverse=True)))
_HONORIFIC_LEAD_RE = re.compile(r"^\s*(?:[가-힣]{2,4}\s+)?리더님[,!]\s*")


def tail_phrase(sentence: str) -> str:
    """문장의 마지막 어절 2개(문장부호·따옴표 제거)."""
    words = re.sub(r"[.!?…\"'“”‘’]", "", sentence or "").split()
    return " ".join(words[-2:]) if words else ""


def lead_tails(text: str) -> list[str]:
    """평서문(되받기)들의 마무리 어구 목록."""
    return [t for t in (tail_phrase(s) for s in split_sentences(text or "") if not is_question(s)) if t]


def find_banned_tail(text: str) -> list[str]:
    out = []
    for s in split_sentences(text or ""):
        if is_question(s):
            continue
        m = _BANNED_TAIL_RE.search(s)
        if m:
            out.append(m.group(0))
    return out


def strip_lead_sentences(text: str, tails: set) -> tuple[str, int]:
    """마무리 어구가 tails 에 있거나 금지 어구를 담은 평서문을 지운다(질문·목록 줄은 보존). 전부 지워지면 '그러셨군요.'."""
    sents = split_sentences(text or "")
    hit = [s for s in sents if not is_question(s) and (tail_phrase(s) in tails or _BANNED_TAIL_RE.search(s))]
    if not hit:
        return text, 0
    out = text
    for x in hit:
        out = out.replace(x, "", 1)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    if not out:
        out = "그러셨군요."
    return out, len(hit)


def starts_with_honorific(text: str) -> bool:
    return bool(_HONORIFIC_LEAD_RE.match(text or ""))


def strip_leading_honorific(text: str) -> tuple[str, bool]:
    """문두 '리더님,'(또는 '박기진 리더님,') 호칭을 뗀다 — 3턴에 1회 규칙."""
    new = _HONORIFIC_LEAD_RE.sub("", text or "", count=1)
    return new, new != (text or "")


# ── 5) (2026-09-22 폐지) 되받기 리드 삭제 trim_lead_sentences — 자른 문장이 어색하다. 되받기는 프롬프트 한 줄이 맡는다. ──


def first_lead(text: str) -> str:
    return _first_sentence(text)


# ── (2026-09-22 폐지) 연결 한 절 템플릿(bridge_keyword·template_anchor_bridged) — 인용 어절 오류("'일들이'와도")가 잦았고,
#    LLM 의 되받기 한 문장이 다리 역할을 한다. 폴백은 template_anchor(질문)만 쓴다. ──


# (2026-10-28 P0-5) 주절 없이 시작하는 질문: 조건절·연결어미로 시작하면 앞 문장이 질문의 일부다.
_DEPENDENT_START_RE = re.compile(
    r"^(있었다면|있으셨다면|있다면|없었다면|했다면|하셨다면|됐다면|되었다면|그렇다면|그랬다면|아니라면|아니면|혹은|또는|"
    r"[가-힣]+(이라면|라면|다면|으면|면),?\s|[가-힣]+(였는지|이었는지|었는지|는지|인지),?\s)")


def starts_without_main_clause(sentence: str) -> bool:
    """'있었다면 어떻게 설득하셨는지' 처럼 조건절·연결 절로 시작하는 문장(앞 절이 잘린 흔적)."""
    return bool(_DEPENDENT_START_RE.match((sentence or "").strip()))


def norm_sentence(s: str) -> str:
    return re.sub(r"[\s.,!?…'\"()]", "", s or "")


_JOSA_AFTER_BUBUN = {"를": "을", "가": "이", "는": "은", "와": "과", "나": "이나", "로": "으로", "란": "이란", "라는": "이라는"}


def strip_sub_name_mentions(text: str, names: list[str]) -> tuple[str, int]:
    """비앵커 프로브 턴의 하위역량 이름 노출을 걷어낸다(2026-09-18, 09-21 보강).
    (a) "'변화관리'와 관련하여, " / "변화관리 측면에서 " 처럼 관련 구절이 따르면 구절째 삭제.
    (b) 따옴표로 이름 전체만 감싼 "'팀워크'이나 장기 성과" 는 '그 부분'으로 치환(조사는 받침에 맞춰 교정 — "팀의 이나" 같은 파손 방지).
    긴 인용구 안의 부분 일치("'프로세스 표준화 작업이 정착'되는")는 건드리지 않는다 — 걷어내면 따옴표가 깨진다."""
    t = text or ""
    n = 0
    _REL = r"(관련하여|관련해서|관련해|측면에서|부분에서|이야기와|말씀과)"
    _JOSA = r"(이나|나|이라는|라는|이란|란|으로|로|과|와|에|의|을|를|은|는|도|이|가)?"
    for v in name_variants(names):
        if len(v) < 3 or v not in t:
            continue
        quoted_rel = re.compile(r"['\"“‘]" + re.escape(v) + r"['\"”’]\s*" + _JOSA + r"\s*" + _REL + r"[,\s]*")
        bare_rel = re.compile(re.escape(v) + r"\s*" + _JOSA + r"\s*" + _REL + r"[,\s]*")
        for pat in (quoted_rel, bare_rel):
            t2, k = pat.subn("", t)
            if k:
                n += k
                t = t2
        quoted = re.compile(r"['\"“‘]" + re.escape(v) + r"['\"”’]" + _JOSA)

        def _rep(m: re.Match) -> str:
            j = m.group(1) or ""
            return "그 부분" + _JOSA_AFTER_BUBUN.get(j, j)
        t2, k = quoted.subn(_rep, t)
        if k:
            n += k
            t = t2
    t = re.sub(r"[ \t]{2,}", " ", t).strip()
    return t, n


_Q_NOISE_RE = re.compile(r"(방금|앞서|아까|조금 전)?\s*(말씀하신|말씀해 ?주신|언급하신)\s*['\"“‘][^'\"”’]{1,10}['\"”’]\s*(과도|와도|과|와)?\s*(이어지는데요|이어지는 부분입니다만|이어서|이어지는데)?[,\s]*"
                          r"|혹시|혹|리더님께서는|리더님은|리더님|그렇다면|그럼|그 결에서 이어 여쭙니다만|그러한 관점에서|최근에|근래에|요즘")


def _question_core(sentence: str) -> str:
    return norm_sentence(_Q_NOISE_RE.sub("", sentence or ""))


def same_question_as_previous(text: str, prev_coach_text: str | None) -> str | None:
    """이번 출력의 질문 문장이 직전 코치 턴의 질문과 (연결 절·'혹시'·호칭을 뺀 뒤) 같으면 그 문장을 돌려준다(2026-09-21).
    사람관리 리플레이 21·22턴: 템플릿 앵커 뒤 LLM 이 같은 앵커를 '혹시'만 바꿔 되물었다."""
    if not prev_coach_text:
        return None
    prev = {_question_core(q) for q in split_sentences(prev_coach_text) if is_question(q)}
    prev = {q for q in prev if len(q) >= 8}
    for q in split_sentences(text or ""):
        if is_question(q) and _question_core(q) in prev:
            return q
    return None


def has_question(text: str) -> bool:
    return any(is_question(x) for x in split_sentences(text))


_INCIDENT_DEMO_RE = re.compile(r"(?:이번|이|해당|그)\s*사건")
_INCIDENT_COUNT_RE = re.compile(r"((?:한|두|세|네|다섯|\d+)\s*)(?:개의\s*)?사건")
_INCIDENT_RE = re.compile(r"사건")


def rewrite_incident_word(text: str | None) -> tuple[str, int]:
    """(2026-11-02 p2f) 코치 발화의 '사건'(BEI 내부어)을 리더 말로 — '이번 사건'→'그 일', '세 사건'→'세 가지', 그 외 '사건'→'일'. (본문, 바꾼 수)
    p2c 25세션 중 12턴이 되받기에 '사건'을 썼다('이번 사건의 중심으로 보입니다', '앞서 말씀하신 세 사건에서는')."""
    t = text or ""
    if "사건" not in t:
        return text or "", 0
    n = len(_INCIDENT_RE.findall(t))
    t = _INCIDENT_DEMO_RE.sub("그 일", t)
    t = _INCIDENT_COUNT_RE.sub(lambda m: f"{m.group(1).strip()} 가지", t)
    t = _INCIDENT_RE.sub("일", t)
    return t, n


_DEMONSTRATIVE_RE = re.compile(r"(그것|그걸|그게|그거|그럴\s*(때|땐)|그런\s*(때|땐)|그러실\s*(때|땐)|그렇게\s*하(니|시니|셨을\s*(때|땐))|그때는|그땐|그\s*일)")


_GENERIC_Q = {"어떻게", "어떠셨", "어떠셨습니까", "어땠", "어땠어요", "어떠셨어요", "받아들였", "받아들였나요", "하셨", "하셨습니까",
              "느끼셨", "느끼셨습니까", "드셨", "되셨", "있으셨", "있으셨을까요", "계셨", "리더님", "리더님께서는", "리더님께서",
              "혹시", "그때", "그때는", "그것", "그걸", "그게", "그거", "그럴", "그런", "그렇게", "팀원", "팀원들", "생각", "마음",
              "어떤", "무엇", "무엇을", "보셨", "하시니", "하시나요", "되었", "됐", "됐습니까", "했", "했습니까"}


def has_bare_demonstrative(question: str, user_text: str | None) -> bool:
    """질문이 대명사로만 대상을 가리키는가 — 인용('…')도, 직전 사용자 발화의 내용 어절도, 문장 자체의 구체 어절(2개 이상)도 없이
    '그것/그럴 때'만 있다. ('크게 실패한 뒤 … 그때는'처럼 문장 안에 대상이 있으면 대명사 단독이 아니다.)"""
    if not _DEMONSTRATIVE_RE.search(question or ""):
        return False
    if re.search(r"['‘\"“][^'’\"”]{2,}['’\"”]", question):
        return False
    user_chunks = {c for c in _content_chunks(user_text or "") if len(c) >= 2}
    q_chunks = [c for c in _content_chunks(question) if len(c) >= 2]
    if user_chunks & set(q_chunks):
        return False
    own_specific = [c for c in q_chunks if c not in _GENERIC_Q and not _DEMONSTRATIVE_RE.fullmatch(c)]
    return len(own_specific) < 2


def bare_demonstrative_questions(text: str, user_text: str | None) -> list[str]:
    return [s for s in split_sentences(text or "") if is_question(s) and has_bare_demonstrative(s, user_text)]


def _josa(word: str, with_final: str, without_final: str) -> str:
    ch = (word or "")[-1:]
    if ch and "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28:
        return with_final
    return without_final


_FRAME_LEAD_RE = re.compile(r"^\s*(먼저 하나 여쭤볼게요\.|가볍게 시작해 볼게요\.|실제 있었던 일로 시작해 볼게요\.|바로 여쭤볼게요\.|"
                            r"이 영역은 이 질문부터요\.)\s*")


def strip_frame_lead(anchor: str) -> str:
    """앵커 프레임의 자체 리드('먼저 하나 여쭤볼게요.')를 뗀다 — 다리 문장과 이중 도입 방지."""
    return _FRAME_LEAD_RE.sub("", anchor or "", count=1)


def anchor_overlap(text: str, anchor_q: str) -> int:
    """출력 질문들과 이번 앵커 질문이 공유하는 내용 어절 수(2자 이상)."""
    qs = " ".join(x for x in split_sentences(text or "") if is_question(x))
    a = {c for c in _content_chunks(anchor_q or "") if len(c) >= 2}
    return len(a & set(_content_chunks(qs)))


# ── 2026-09-29 자기관리 재주행: 지시어 허공·억지 다리·정의→앵커 다리 ──
_NP_STOP = {"리더", "자신", "저", "제", "저희", "우리", "팀원", "팀원들", "아무도", "다들", "요즘", "그냥", "정말", "진짜",
            "사실", "원래", "오히려", "모두", "다", "뭐", "그거", "이거", "그게", "이게", "그런것", "그런거", "경우", "때"}
# 감정·상태 형용사 어간 — '서운했죠'의 '서운'은 사건 명사가 아니다(결과 질문 대상 X)
_NP_EMOTION = {"서운", "답답", "속상", "섭섭", "힘들", "불편", "미안", "당황", "억울", "뿌듯", "행복", "피곤", "귀찮", "심란", "허탈", "민망"}
# 가벼운 목적어('신경을 쓰다', '생각을 하다') — 핵심 명사가 아니다
_NP_LIGHT = {"신경", "생각", "말", "얘기", "일", "것", "거", "마음", "노력"}
_NP_VERB_NOUN_RE = re.compile(r"^(.{2,6}?)(하자고|하자|하고|해서|했는데|했고|했어요|했죠|하는|하기|하려고|하셨|했|하면)$")
_NP_OBJ_RE = re.compile(r"^(.{2,8}?)(을|를)$")
_NP_SUBJ_RE = re.compile(r"^(.{2,8}?)(이|가|은|는)$")


def _np_tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,.!?…~\"'‘’“”()\[\]/·*-]+", text or "") if t]


def key_noun_phrase(user_text: str | None) -> str:
    """직전 사용자 발화의 핵심 명사구 하나(2~12자). '회식하자고' → '회식', '일관성이 가장 중요' → '일관성'.
    결과 질문·정의 다리에 넣는 용도 — 대명사만으로 가리키지 않게."""
    toks = _np_tokens(user_text)
    if not toks:
        return ""
    # 1) '… 가장 중요/핵심' 앞의 주어 명사 (정의 답변)
    for i, t in enumerate(toks):
        if t.startswith(("중요", "핵심")) and i > 0:
            j = i - 1
            if toks[j] == "가장" and j > 0:
                j -= 1
            m = _NP_SUBJ_RE.match(toks[j])
            if m and m.group(1) not in _NP_STOP:
                return m.group(1)
    # 2) 목적어(을/를) — 마지막 것, 앞 어절이 명사 수식이면 붙인다
    objs = []
    for i, t in enumerate(toks):
        m = _NP_OBJ_RE.match(t)
        if m and m.group(1) not in _NP_STOP and m.group(1) not in _NP_LIGHT:
            np_ = m.group(1)
            if i > 0 and len(toks[i - 1]) <= 4 and not re.search(r"(다|요|고|서|며|면|는|은|을|를|이|가|에|게|도|만|죠|니)$", toks[i - 1]) \
                    and toks[i - 1] not in _NP_STOP:
                np_ = f"{toks[i - 1]} {np_}"
            objs.append(np_)
    if objs:
        return objs[-1][:12]
    # 3) 명사+하다 동사('회식하자고')
    for t in toks:
        m = _NP_VERB_NOUN_RE.match(t)
        if m and m.group(1) not in _NP_STOP and m.group(1) not in _NP_EMOTION:
            return m.group(1)
    # 4) 주어·주제(이/가/은/는)
    for t in toks:
        m = _NP_SUBJ_RE.match(t)
        if m and m.group(1) not in _NP_STOP and not re.search(r"(하|되|있|없|같)$", m.group(1)):
            return m.group(1)
    return ""


def followup_from_user(user_text: str | None) -> str:
    """대명사 단독 질문의 잔존 교체문(결과 강제 턴이 아닐 때) — 리더가 쓴 말을 받아 한 걸음 더 묻는다."""
    np_ = key_noun_phrase(user_text)
    if not np_:
        t = re.sub(r"\s+", " ", (user_text or "").strip())[:14].rstrip(" .,!?")
        np_ = t
    if not np_:
        return "방금 말씀하신 장면을 조금 더 구체적으로 들려주시겠어요?"
    return f"'{np_}'{_josa(np_, '이라고', '라고')} 하신 부분을 조금 더 구체적으로 들려주시겠어요?"


def drop_question_sentences(text: str) -> tuple[str, int]:
    """본문의 물음표 문장을 지운다 — 줄 단위로 처리해 목록·문단 줄바꿈을 보존. ALIGN 본문 — 질문은 뒤에 붙는 앵커 하나뿐."""
    n = 0
    lines = []
    for line in (text or "").split("\n"):
        sents = split_sentences(line)
        kept = [x for x in sents if not is_question(x)]
        n += len(sents) - len(kept)
        if sents and not kept:
            continue          # 질문뿐인 줄은 통째로 뺀다
        lines.append(" ".join(kept) if len(kept) != len(sents) else line)
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, n
