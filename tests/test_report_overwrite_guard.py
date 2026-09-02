"""H1: 재분석 시 기존 리포트 처리 — 교정본 보호 + 생성 후 삭제 순서.

- protected_human_edited: 관리자 교정본(is_human_edited)이 있으면 최신 1건을 돌려
  analyze 가 재분석을 스킵하게 한다(골든 쌍 ai_original ↔ 교정본 보존).
- analyze 본문은 '새 리포트 db.add → 구 리포트 db.delete → 단일 commit' 순서다
  (분석 전 삭제·커밋으로 실패 시 리포트가 사라지던 순서를 뒤집음). 이 순서는
  소스 검사로 고정한다(DB 없는 회귀).
"""
import inspect
from datetime import datetime
from types import SimpleNamespace as NS

from diag_project.routes import reports as R


def test_no_edited_returns_none():
    assert R.protected_human_edited([]) is None
    assert R.protected_human_edited([NS(is_human_edited=False)]) is None
    assert R.protected_human_edited(None) is None


def test_latest_edited_is_protected():
    old = NS(id="old", is_human_edited=True, edited_at=datetime(2026, 1, 1),
             created_at=datetime(2025, 12, 1))
    new = NS(id="new", is_human_edited=True, edited_at=datetime(2026, 2, 1),
             created_at=datetime(2025, 12, 2))
    plain = NS(id="plain", is_human_edited=False, edited_at=None,
               created_at=datetime(2026, 3, 1))
    assert R.protected_human_edited([plain, old, new]).id == "new"


def test_analyze_deletes_old_after_add_in_same_transaction():
    src = inspect.getsource(R.analyze_session)
    i_add = src.index("db.add(new_report)")
    i_del = src.index("await db.delete(_old)")
    assert i_add < i_del, "구 리포트 삭제는 새 리포트 add 이후여야 한다"
    # add 와 delete 사이에 commit 이 없어야 단일 트랜잭션이다.
    assert "await db.commit()" not in src[i_add:i_del]
    # 분석 이전 구간(existing_reports 조회 ~ generate_diagnosis_result)에 삭제 없음
    i_q = src.index("existing_reports = ")
    i_llm = src.index("generate_diagnosis_result")
    assert "db.delete(" not in src[i_q:i_llm]
