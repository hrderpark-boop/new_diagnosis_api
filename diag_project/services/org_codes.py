"""조직 참여 코드(AS1 형식) 규칙. DB·HTTP 와 무관한 순수 함수만 둔다(테스트 고정용).

규칙
  - 회사 접두어: 영문 대문자 1~3자 (예: A, ACM)
  - 본부 코드  : 영문 대문자 1~2자 (예: S)  → 본부 참여 코드 = 접두어 + 본부 코드 (AS)
  - 실 코드    : 영문 대문자 1~2자 (예: M)  → 실 참여 코드   = 본부 참여 코드 + 실 코드 (ASM). 실은 선택 단계
  - 팀 번호    : 1~99                       → 팀 참여 코드   = 상위(본부 또는 실) 코드 + 번호 (AS1, ASM1)
  - 코드는 전 고객사에서 유일해야 한다(겹치면 등록 단계에서 거부).
  - 접두어끼리는 서로의 앞부분이 될 수 없다(A 와 AS 를 함께 쓰면 'AS1' 이 어느 회사인지 모호해진다).
"""
import re
from typing import Iterable, Optional

PREFIX_RE = re.compile(r"^[A-Z]{1,3}$")
DIVISION_RE = re.compile(r"^[A-Z]{1,2}$")
TEAM_MIN, TEAM_MAX = 1, 99


def normalize(s: Optional[str]) -> str:
    """로그인 게이트와 같은 정규화: 앞뒤 공백 제거 + 대문자."""
    return (s or "").strip().upper()


def validate_prefix(prefix: str, other_prefixes: Iterable[str] = ()) -> Optional[str]:
    """접두어 검증. 문제가 있으면 사용자에게 보일 사유, 없으면 None."""
    p = normalize(prefix)
    if not PREFIX_RE.match(p):
        return "회사 접두어는 영문 1~3자입니다."
    for o in other_prefixes:
        o = normalize(o)
        if not o:
            continue
        if o == p:
            return f"이미 다른 고객사가 쓰는 접두어입니다({o})."
        if o.startswith(p) or p.startswith(o):
            return f"다른 고객사 접두어({o})와 앞부분이 겹쳐 코드가 모호해집니다."
    return None


def validate_division_code(short: str) -> Optional[str]:
    s = normalize(short)
    if not DIVISION_RE.match(s):
        return "본부 코드는 영문 1~2자입니다."
    return None


def validate_office_code(short: str) -> Optional[str]:
    s = normalize(short)
    if not DIVISION_RE.match(s):
        return "실 코드는 영문 1~2자입니다."
    return None


def office_code(division_full_code: str, short: str) -> str:
    return normalize(division_full_code) + normalize(short)


def division_code(prefix: str, short: str) -> str:
    return normalize(prefix) + normalize(short)


def next_team_number(existing_numbers: Iterable[str]) -> int:
    """같은 본부의 기존 팀 번호들 다음 번호. 빈 번호를 메우지 않고 최댓값 + 1."""
    nums = [int(n) for n in existing_numbers if str(n).isdigit()]
    return (max(nums) + 1) if nums else TEAM_MIN


def validate_team_number(n: int) -> Optional[str]:
    if not (TEAM_MIN <= int(n) <= TEAM_MAX):
        return f"팀 번호는 {TEAM_MIN}~{TEAM_MAX} 사이입니다."
    return None


def team_code(division_full_code: str, number: int) -> str:
    return normalize(division_full_code) + str(int(number))


# ── 자동 발급(2026-10-29): 사람이 코드를 고르지 않아도 되도록 비어 있는 다음 코드를 고른다 ──
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _letter_seq(max_len: int):
    """A..Z, AA..ZZ (, AAA..ZZZ) 순서."""
    for ch in _LETTERS:
        yield ch
    if max_len >= 2:
        for a in _LETTERS:
            for b in _LETTERS:
                yield a + b
    if max_len >= 3:
        for a in _LETTERS:
            for b in _LETTERS:
                for c in _LETTERS:
                    yield a + b + c


def next_letter_code(used: Iterable[str], max_len: int = 2) -> str:
    """같은 상위 안에서 아직 안 쓴 다음 영문 코드(본부·실용). A, B, … Z, AA, AB …"""
    taken = {normalize(u) for u in used if u}
    for code in _letter_seq(max_len):
        if code not in taken:
            return code
    raise ValueError("더 이상 쓸 수 있는 코드가 없습니다.")


def prefix_candidates(hints: Iterable[str]) -> list:
    """회사 코드·이름에서 접두어 후보를 뽑는다. 영문만 남겨 앞 1~3자(예: 'HCS-01' → H, HC, HCS).
    한글 이름처럼 영문이 없으면 후보가 없다(그때는 A, B, … 순서로)."""
    out = []
    for h in hints:
        letters = "".join(ch for ch in normalize(h) if "A" <= ch <= "Z")
        for n in (1, 2, 3):
            if len(letters) >= n and letters[:n] not in out:
                out.append(letters[:n])
    # 짧은 것부터(같은 길이면 힌트 순서)
    return sorted(out, key=len)


def auto_prefix(other_prefixes: Iterable[str], hints: Iterable[str] = ()) -> str:
    """다른 고객사 접두어와 겹치지 않는(앞부분 포함) 가장 짧은 접두어.
    회사 코드·이름의 영문 후보를 먼저 쓰고, 없거나 다 겹치면 A, B, … 순서."""
    others = [normalize(o) for o in other_prefixes if o]
    for code in prefix_candidates(hints):
        if validate_prefix(code, others) is None:
            return code
    for code in _letter_seq(3):
        if validate_prefix(code, others) is None:
            return code
    raise ValueError("쓸 수 있는 접두어가 없습니다.")
