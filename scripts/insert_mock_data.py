"""검증용 mock 데이터 DB 삽입.

coach (없으므로 생성) + session + BEI 대화 ChatMessages 삽입.
Event 객체는 불필요 — analyze 엔드포인트는 ChatMessage 텍스트만 사용.

실행:
    cd /Users/daniel/python_new/new_diagnosis_api
    /Users/daniel/python_new/.venv/bin/python scripts/insert_mock_data.py
"""

import asyncio
import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.database import async_session as async_session_maker
from diag_project.models.coach import Coach
from diag_project.models.diagnosis_session import DiagnosisSession, ChatMessage
from diag_project.models.participant import Participant

MOCK_COACH_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
MOCK_SESSION_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")

# 실제 participant (박기진)
PARTICIPANT_EMAIL = "hrder.park@gmail.com"


MOCK_CONVERSATION = [
    # 라포
    ("model", "[코치] 안녕하세요 리더님, 코치 Ella입니다. 오늘 진단에 참여해 주셔서 감사합니다."),
    ("user",  "안녕하세요! 박기진입니다. 잘 부탁드려요."),
    ("model", "네, 기진 리더님 반갑습니다. 오늘 진단에서 특별히 기대하시는 게 있으세요?"),
    ("user",  "리더십 역량을 객관적으로 파악하고 싶어요. 제가 잘 하고 있는지 확인하고 싶습니다."),
    # INTRO
    ("model", "좋은 동기네요. 진단은 5개 영역으로 이루어져 있고 각 영역 약 30분씩 진행됩니다."),
    ("user",  "네, 시작할게요."),
    # 조직관리
    ("model", "첫 번째 영역인 조직관리부터 시작할게요. 리더님은 조직관리를 어떻게 정의하시나요?"),
    ("user",  "조직관리는 팀이 목표를 향해 효율적으로 움직이도록 방향을 잡아주는 것이라고 생각해요."),
    ("model", "좋은 정의네요. 최근에 팀의 비전이나 목표를 공유하셨던 경험이 있으시면 말씀해 주세요."),
    ("user",  "올해 초에 팀 연간 목표 수립 회의를 진행했어요. 팀원이 8명인데 각자가 회사 전략과 자신의 일을 연결하지 못해 동기 부여가 낮다고 느꼈어요."),
    ("model", "구체적으로 어떻게 연결하셨는지 말씀해 주시겠어요?"),
    ("user",  "회사의 3년 로드맵을 슬라이드로 정리해서 팀원들에게 공유했고, 각자 자신의 업무가 어떤 전략에 기여하는지 빈 종이에 직접 써보게 했어요. 처음엔 막막해했지만 30분 토론 후 대부분이 연결고리를 찾았어요."),
    ("model", "그 결과는 어땠나요?"),
    ("user",  "팀원 6명이 자신의 일에 주인의식을 갖게 됐다고 피드백을 줬어요. 다음 분기 회의에서 자발적인 제안이 3배 늘었고 성과 지표도 15% 개선됐습니다."),
    # 성과관리
    ("model", "다음은 성과관리 영역이에요. 팀의 성과를 측정하고 관리한 경험을 말씀해 주세요."),
    ("user",  "작년에 팀 KPI 체계를 새로 만들었어요. 기존에는 결과 지표만 있어서 중간에 문제를 파악하기 어려웠거든요."),
    ("model", "어떻게 새 KPI 체계를 설계하셨나요?"),
    ("user",  "팀원들과 워크숍을 3회 진행해서 선행 지표(activity KPI)와 후행 지표(output KPI)를 구분해서 정의했어요. 주간 스탠드업에서 선행 지표를 추적하도록 바꿨습니다."),
    ("model", "어떤 어려움이 있었나요?"),
    ("user",  "일부 팀원이 숫자로 성과를 측정하는 걸 부담스러워했어요. 평가받는다는 느낌을 주지 않으려고 '학습 지표'라고 명명하고 성장을 보는 도구라고 설명했습니다."),
    ("model", "결과는 어떻게 됐나요?"),
    ("user",  "반기 성과 리뷰에서 목표 달성률이 팀 평균 82%에서 94%로 올랐고, 팀원들의 자기평가 정확도도 높아졌어요."),
    # 사람관리
    ("model", "사람관리 영역으로 넘어갈게요. 팀원 육성이나 코칭을 하신 경험 중 기억에 남는 것이 있으신가요?"),
    ("user",  "2년 전에 입사 1년 차 팀원이 자신감이 많이 낮았어요. 실수를 두려워해서 보고를 자꾸 미루는 패턴이 있었습니다."),
    ("model", "어떻게 접근하셨나요?"),
    ("user",  "매주 1:1 미팅을 30분씩 진행했어요. 처음엔 업무 진행 상황을 체크했지만 나중엔 그 팀원이 배운 것과 어려운 점을 스스로 정리하는 시간으로 바꿨습니다."),
    ("model", "구체적으로 어떤 변화가 있었나요?"),
    ("user",  "3개월 후 그 팀원이 스스로 개선 아이디어를 가져오기 시작했고, 6개월 후에는 신규 프로젝트 리드를 맡았습니다. 지금은 팀에서 가장 성장이 빠른 멤버가 됐어요."),
    # 일관리
    ("model", "일관리 영역이에요. 복잡한 프로젝트를 계획하고 실행한 경험을 말씀해 주세요."),
    ("user",  "지난해에 3개 팀이 협업하는 크로스펑셔널 프로젝트를 맡았어요. 각 팀의 우선순위가 달라서 조율이 힘들었습니다."),
    ("model", "어떻게 조율하셨나요?"),
    ("user",  "가장 먼저 각 팀 리더와 개별 면담을 해서 실제 우선순위와 제약사항을 파악했어요. 그 뒤에 공유된 목표를 정의하고 각 팀이 기여하는 부분을 명확히 했습니다."),
    ("model", "구체적인 결과를 말씀해 주세요."),
    ("user",  "원래 6개월 예상 프로젝트를 4.5개월에 완료했어요. 핵심 지표(전환율)가 목표 대비 120% 달성됐고, 협업 팀들의 만족도 조사에서 4.2/5.0 점이 나왔습니다."),
    # 자기관리
    ("model", "마지막으로 자기관리 영역이에요. 리더로서 자신을 관리하거나 성장시키기 위해 하신 노력을 말씀해 주세요."),
    ("user",  "2년 전부터 매월 독서 리뷰와 회고를 합니다. 조직심리학, 코칭 관련 책을 읽고 실제 적용한 것과 아닌 것을 기록해요."),
    ("model", "그게 리더십에 어떤 영향을 줬나요?"),
    ("user",  "예전엔 직관으로 의사결정을 많이 했는데, 이제는 근거를 명확히 하려는 습관이 생겼어요. 팀원들이 '리더님 결정은 이유가 명확하다'고 이야기해줍니다."),
    ("model", "어렵거나 실패했던 자기관리 경험도 있으신가요?"),
    ("user",  "작년에 번아웃을 경험했어요. 팀 성과에만 집중하다 보니 제 체력 관리를 못 했고, 결국 2주 반 쉬었습니다. 그 이후로 업무 시간 외에 운동과 수면을 관리하고 있어요."),
    ("model", "오늘 5개 영역 진단을 모두 마쳤습니다. 결과 분석을 진행하겠습니다."),
]


async def main():
    async with async_session_maker() as db:
        # 1. participant 조회
        res = await db.execute(
            select(Participant).where(Participant.email == PARTICIPANT_EMAIL)
        )
        participant = res.scalars().first()
        if not participant:
            print(f"❌ participant '{PARTICIPANT_EMAIL}' 없음. DB 초기화 필요.")
            return
        print(f"✅ participant: {participant.name} ({participant.id})")

        # 2. mock coach 삽입 (없는 경우만)
        existing_coach = await db.get(Coach, MOCK_COACH_ID)
        if not existing_coach:
            coach = Coach(
                id=MOCK_COACH_ID,
                name="Mock Coach Ella",
                email="mock-ella@test.internal",
                description="검증용 mock 코치",
                user_id=None,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(coach)
            await db.flush()
            print(f"✅ mock coach 삽입: {MOCK_COACH_ID}")
        else:
            print(f"✅ mock coach 이미 존재: {MOCK_COACH_ID}")

        # 3. mock session 삽입 (없는 경우만)
        existing_session = await db.get(DiagnosisSession, MOCK_SESSION_ID)
        if not existing_session:
            session = DiagnosisSession(
                id=MOCK_SESSION_ID,
                user_id=participant.id,
                coach_id=MOCK_COACH_ID,
                status="completed",
                current_topic="Completed",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(session)
            await db.flush()
            print(f"✅ mock session 삽입: {MOCK_SESSION_ID}")
        else:
            print(f"✅ mock session 이미 존재: {MOCK_SESSION_ID}")

        # 4. ChatMessage 삽입 (없는 경우만)
        existing_msgs = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == MOCK_SESSION_ID)
        )
        if existing_msgs.scalars().first():
            print("✅ ChatMessage 이미 존재. 스킵.")
        else:
            base_time = datetime.now() - timedelta(hours=2)
            for i, (role, content) in enumerate(MOCK_CONVERSATION):
                msg = ChatMessage(
                    id=uuid.uuid4(),
                    session_id=MOCK_SESSION_ID,
                    role=role,
                    content=content,
                    chapter=None,
                    created_at=base_time + timedelta(minutes=i * 3),
                )
                db.add(msg)
            print(f"✅ ChatMessage {len(MOCK_CONVERSATION)}개 삽입")

        await db.commit()
        print(f"\n✅ Mock 데이터 준비 완료")
        print(f"   SESSION_ID: {MOCK_SESSION_ID}")
        print(f"\n다음 실행: python scripts/run_report_pipeline.py")


if __name__ == "__main__":
    asyncio.run(main())
