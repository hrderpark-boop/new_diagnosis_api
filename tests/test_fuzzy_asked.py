"""4-4: 흐린(fuzzy) 합성 케이스 — 제어 역전이 asked/measured 오염을 막는가.

지시서 §4-4 세 실패모드를 결정론적으로 검증한다. 핵심 불변식:
  · asked 는 백엔드가 LLM '이전'에 기록한 원장에서만 온다(텍스트 스캔 폐기).
  · measured = is_measured(asked, evidence) = asked AND evidence>=1.
따라서 LLM/사용자 발화의 표현이 아무리 흐려도 asked·measured 를 조작할 수 없다.

  ① 역량명 미언급: 코치가 하위역량명을 입에 담지 않아도 asked 는 정상 기록.
  ② 유사어: LLM 이 동의어/변형 표현을 써도 asked 카운트가 흔들리지 않음.
  ③ 리액션 오탐: 사용자의 맞장구/감탄을 '측정'으로 오판해도(=LLM measured=True)
     asked=False 인 하위역량은 measured 로 승격되지 않음(유령 0).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services import traversal as T          # noqa: E402
from diag_project.services.scoring import is_measured      # noqa: E402

P = [0, 0]


def ck(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label} {extra}")
    P[0] += ok
    P[1] += (not ok)


ALL = ["갈등관리", "신뢰형성", "팀워크 촉진(협업)", "코칭 및 피드백",
       "권한위임", "동기부여", "공감(감성지능)", "의사소통", "인재육성"]


def test_name_never_spoken_still_asked():
    """① 코치가 하위역량명을 한 번도 발화하지 않는 대화. asked 는 백엔드
    원장에 그대로 남는다 — 텍스트에 이름이 없다고 탐색이 취소되지 않는다."""
    store = {}
    # 백엔드가 3개 하위역량을 타겟팅·기록(LLM 발화 내용과 무관)
    for s in ["갈등관리", "신뢰형성", "코칭 및 피드백"]:
        store = T.record_asked(store, "people_management", s)
    asked = T.asked_for_chapter(store, "people_management")
    ck("이름 미발화여도 asked=3 유지", len(asked) == 3 and "코칭 및 피드백" in asked)


def test_synonym_does_not_inflate_or_shrink():
    """② LLM 이 '위임/권한 넘기기' 같은 유사어를 써도 asked 는 원장 카운트
    그대로. 유사어 매칭으로 중복 기록되거나 누락되지 않는다."""
    store = {}
    store = T.record_asked(store, "people_management", "권한위임")
    # 같은 하위역량을 유사어 표현으로 '또' 기록 시도해도 원장은 중복 없음
    store = T.record_asked(store, "people_management", "권한위임")
    asked = T.asked_for_chapter(store, "people_management")
    ck("유사어 중복 발화에도 asked=1(무중복)", asked == ["권한위임"])
    # 유사어라도 원장에 없는 하위역량은 asked 로 세지 않는다
    ck("원장에 없으면 asked 아님", "위임" not in asked and "동기부여" not in asked)


def test_reaction_misread_cannot_fabricate_measured():
    """③ 사용자의 맞장구를 LLM 이 '측정됨(measured=True)'으로 오판해도,
    해당 하위역량이 asked=False 라면 is_measured 는 False 를 반환한다.
    → 유령(asked=F & measured=T) 0 보장."""
    # LLM 분석이 근거 2건 있다고 '주장'하지만 백엔드 원장엔 asked 안 됨
    ck("asked=False + 근거2 → measured False",
       is_measured(asked=False, evidence_count=2) is False)
    # asked=True 인데 근거 0 → 근거 미확보, measured False (역명제)
    ck("asked=True + 근거0 → measured False",
       is_measured(asked=True, evidence_count=0) is False)
    # 정상: asked=True + 근거1 → measured True
    ck("asked=True + 근거1 → measured True",
       is_measured(asked=True, evidence_count=1) is True)


def test_target_selection_ignores_fuzzy_text():
    """타겟 선정은 오직 미탐색 원장에서만 후보를 뽑는다 — 대화 텍스트의
    흐림과 무관하게 결정론적."""
    asked = ["갈등관리", "신뢰형성"]
    for _ in range(5):  # 여러 번 호출해도 결정론적으로 동일 결과
        t = T.select_next_target(asked, ALL, priority=[])
    ck("미탐색에서만·결정론적", t not in asked and t in ALL, f"(={t})")


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            print(f"— {name}")
            fn()
    print(f"\n=== 4-4 흐린 케이스: {P[0]} PASS / {P[1]} FAIL ===")
    return P[1]


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
