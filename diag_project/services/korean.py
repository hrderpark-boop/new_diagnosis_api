"""한국어 표기 보조 — 조사 자동 선택.

템플릿에 챕터명·하위역량명을 삽입할 때 뒤따르는 조사(을/를, 은/는, 이/가,
과/와, 으로/로)를 앞 단어의 받침 유무로 고른다. ("성과관리을" 같은 오류 방지)
프롬프트(layer3)와 시스템 템플릿(intro_messages) 이 같은 함수를 쓴다.
"""


def get_josa(word: str, josa: str) -> str:
    """앞 단어의 받침(종성) 유무로 올바른 조사 선택.

    josa 는 '받침있을때/받침없을때' 형식 문자열:
      '을/를', '이/가', '은/는', '과/와', '으로/로', '이라는/라는' 등.

    예)
      get_josa('성과관리', '을/를') -> '를'   (리: 받침 없음)
      get_josa('직원',     '을/를') -> '을'   (원: ㄴ받침)
      get_josa('사람관리', '이/가') -> '가'
      get_josa('서울',     '으로/로') -> '로'  (울: ㄹ받침 특례)

    한글 음절이 아닌 문자로 끝나면 받침 없는 형태를 기본값으로 반환한다.
    따옴표로 감싼 단어("'성과관리'")도 마지막 한글 음절을 찾아 판정한다.
    """
    with_batchim, without_batchim = josa.split("/")
    if not word:
        return without_batchim

    # 따옴표·공백 등 뒤에 붙은 비한글 문자를 건너뛰고 마지막 한글 음절을 본다.
    last_hangul = None
    for ch in reversed(word):
        if 0xAC00 <= ord(ch) <= 0xD7A3:
            last_hangul = ch
            break
        if ch.isalnum():
            break  # 영문/숫자로 끝나면 받침 없음 취급
    if last_hangul is None:
        return without_batchim

    jongseong = (ord(last_hangul) - 0xAC00) % 28
    # '으로/로' 특례: 받침이 없거나(0) ㄹ받침(8)이면 '로'.
    if with_batchim == "으로":
        return without_batchim if jongseong in (0, 8) else with_batchim
    return without_batchim if jongseong == 0 else with_batchim


def with_josa(word: str, josa: str, quote: bool = False) -> str:
    """단어+조사를 한 번에. quote=True 면 단어를 작은따옴표로 감싼다.

    예) with_josa('성과관리', '을/를', quote=True) -> "'성과관리'를"
    """
    core = f"'{word}'" if quote else word
    return f"{core}{get_josa(word, josa)}"
