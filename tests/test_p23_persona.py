"""(2026-10-22 P2-3) 페르소나 복원 — 되받기 상한·관찰 문장·전환 다리·ALIGN 고정 다리 (LLM·DB 없음)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.data.competencies import SUBCOMPETENCY_ANCHOR_QUESTIONS # noqa: E402

from diag_project.prompts.phase3a import layer3_state as L  # noqa: E402
from diag_project.services import output_guard as G  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER = "선임은 속도를 원했고 저는 준비를 택했어요. 그래서 두 달 뒤에 오픈했습니다."


















def test_rapport_fixed_question_binds_persona_name():
    """(2026-10-23 핫픽스) 9fad8ae 회귀: _pl_r("role_q") 가 persona_line 별칭이라 TypeError → 운영 라포 3턴 500. 이름을 묶은 호출자여야 한다."""
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert "def _pl_r(key: str, **fmt) -> str:" in src and "_persona_line_r(_persona_name_r, key, **fmt)" in src
    assert "import persona_line as _pl_r" not in src
    # 다른 별칭은 모두 (이름, 키) 두 인자로 부른다
    import re
    for alias in ("_pl_i", "_pl_q", "_pl_a", "_pl_om"):
        for m in re.finditer(alias + r"\(([^)]*)\)", src):
            assert "coach_persona" in m.group(1), (alias, m.group(0)[:80])
