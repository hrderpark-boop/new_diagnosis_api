"""Mock 데이터로 채점 + 리포트 파이프라인 직접 실행.

insert_mock_data.py 실행 후 사용.

실행:
    cd /Users/daniel/python_new/new_diagnosis_api
    /Users/daniel/python_new/.venv/bin/python scripts/run_report_pipeline.py
"""

import asyncio
import uuid
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from diag_project.database import async_session as async_session_maker
from diag_project.models.diagnosis_session import DiagnosisSession, ChatMessage
from diag_project.models.diagnosis_report import DiagnosisReport
from diag_project.models.participant import Participant
from diag_project.llm_service import GeminiService

MOCK_SESSION_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")


async def main():
    async with async_session_maker() as db:
        # 1. 세션 + 사용자 확인
        session = await db.get(DiagnosisSession, MOCK_SESSION_ID)
        if not session:
            print("❌ mock session 없음. 먼저 insert_mock_data.py 실행 필요.")
            return

        user = await db.get(Participant, session.user_id)
        user_name = user.name if user else "박기진"

        msgs_res = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == MOCK_SESSION_ID)
            .order_by(ChatMessage.created_at.asc())
        )
        messages = msgs_res.scalars().all()
        print(f"✅ ChatMessage {len(messages)}개 로드 (user={user_name})")

        history = [{"role": m.role, "parts": m.content} for m in messages]

        # 2. 기존 리포트 확인
        existing_res = await db.execute(
            select(DiagnosisReport).where(DiagnosisReport.session_id == MOCK_SESSION_ID)
        )
        existing_report = existing_res.scalars().first()
        if existing_report:
            print(f"ℹ️  기존 리포트 있음 (id={existing_report.id}). 덮어씁니다.\n")
            await db.delete(existing_report)
            await db.flush()

        # 3. LLM 파이프라인 실행
        llm = GeminiService()
        print("=" * 60)
        print("Phase 2+3 CoT 채점/리포트 파이프라인 실행")
        print("(Step 1: 발화분류 → Step 2: 역량별 분석 → Step 3: 종합)")
        print("=" * 60)

        try:
            result = await llm.generate_diagnosis_result(
                history=history,
                user_name=user_name,
            )
        except Exception as e:
            print(f"\n❌ generate_diagnosis_result 실패: {e}")
            import traceback; traceback.print_exc()
            return

        # 4. 결과 요약 출력
        print("\n✅ 파이프라인 완료\n")
        print(f"  총점: {result.get('total_score')}")
        rc = result.get("radar_chart", {})
        print("  레이더 점수:")
        for k, v in rc.items():
            print(f"    {k}: {v}")

        arch = result.get("archetype", {})
        print(f"\n  아키타입: {arch.get('name')} — {arch.get('description')}")
        print(f"\n  사각지대: {result.get('blind_spot', '-')[:120]}...")
        idp = result.get("idp", [])
        print(f"\n  IDP ({len(idp)}개):")
        for item in idp:
            print(f"    - {item[:80]}...")
        kw = result.get("top_keywords", [])
        print(f"\n  키워드: {kw}")
        print(f"\n  요약 (앞 200자):")
        print(f"    {result.get('feedback_summary', '')[:200]}...")

        # 5. DB 저장
        total_score = result.get("total_score", 0.0)
        new_report = DiagnosisReport(
            id=uuid.uuid4(),
            session_id=MOCK_SESSION_ID,
            user_id=session.user_id,
            coach_id=session.coach_id,
            summary=result.get("feedback_summary", "-"),
            scores=result,
            total_score=total_score,
            top_competency="-",
            bottom_competency="-",
            feedback="-",
            recommended_action="-",
            created_at=__import__("datetime").datetime.now(),
        )
        db.add(new_report)
        await db.commit()
        print(f"\n✅ DiagnosisReport DB 저장 완료 (id={new_report.id})")
        print(f"\n확인: GET /api/v1/reports/{MOCK_SESSION_ID}")


if __name__ == "__main__":
    asyncio.run(main())
