# diag_project/services/analysis_service.py

import json
import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Dict, Any

from diag_project.models.diagnosis_session import DiagnosisSession, ChatMessage
from diag_project.models.diagnosis_result import DiagnosisResult
from diag_project.llm_service import GeminiService
from diag_project.data.competencies import COMPETENCY_FRAMEWORK

# [추가] 신규 SDK 타입
from google.genai import types

logger = logging.getLogger(__name__)

class AnalysisService:
    def __init__(self):
        # llm_service에서 이미 신규 라이브러리로 초기화된 인스턴스를 사용
        self.llm = GeminiService()

    async def analyze_session(self, db: AsyncSession, session_id: UUID) -> DiagnosisResult:
        # 1. 대화 기록 가져오기
        result = await db.execute(select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at))
        messages = result.scalars().all()
        
        if not messages or len(messages) < 2:
             transcript = "대화 내용이 부족합니다. 모든 역량을 3점(보통) 수준으로 가정하고 분석하세요."
        else:
             transcript = "\n".join([f"[{msg.role.upper()}]: {msg.content}" for msg in messages])

        # 2. 역량 구조 만들기
        structure_guide = ""
        for k, v in COMPETENCY_FRAMEWORK.items():
            sub_list = ", ".join([f"{ik}({iv['name']})" for ik, iv in v['indicators'].items()])
            structure_guide += f"- {k} ({v['name']}): 하위지표 [{sub_list}]\n"

        # 3. 정밀 분석 프롬프트
        prompt = f"""
        당신은 HR Assessment Center 평가관입니다.
        대화 기록을 분석하여 리더십 역량 진단 데이터를 JSON으로 생성하세요.

        [평가 기준]
        {structure_guide}

        [대화 기록]
        {transcript}

        [임무]
        1. 5개 대분류 역량 점수 (1~5점)
        2. 각 하위 지표 점수
        3. 피드백 (종합 코멘트, 세부 분석, 개선 제언, 근거)
        4. 근거(Evidence)는 사용자의 발언을 인용할 것.

        [출력 JSON 구조 준수]
        {{
            "scores": {{ "organization_management": 3.5, ... }},
            "details": {{
                "organization_management": {{
                    "sub_radar": [ {{"subject": "...", "A": 3, "fullMark": 5}} ],
                    "analysis": {{ "summary": "...", "sub_comments": "...", "suggestion": "...", "evidence": "..." }}
                }}
            }},
            "summary": {{ "strengths": [], "weaknesses": [], "overall_feedback": "..." }}
        }}
        """

        try:
            # [수정] 신규 SDK 방식 호출
            response = await self.llm.client.aio.models.generate_content(
                model=self.llm.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            
            cleaned_json = self.llm._clean_json_text(response.text)
            analysis_data = json.loads(cleaned_json)

        except Exception as e:
            logger.error(f"AI 분석 실패: {e}")
            return None

        # 4. 비교 데이터 생성
        my_scores = analysis_data.get("scores", {})
        my_avg = round(sum(my_scores.values()) / 5, 1) if my_scores else 0

        chart_data = {
            "radar_chart": [
                {"subject": "조직관리", "A": my_scores.get("organization_management", 0), "fullMark": 5},
                {"subject": "성과관리", "A": my_scores.get("performance_management", 0), "fullMark": 5},
                {"subject": "사람관리", "A": my_scores.get("people_management", 0), "fullMark": 5},
                {"subject": "일관리", "A": my_scores.get("work_management", 0), "fullMark": 5},
                {"subject": "자기관리", "A": my_scores.get("self_management", 0), "fullMark": 5},
            ],
            "comparison": {
                "my_score": my_avg,
                "team_avg": 3.8,
                "division_avg": 3.6,
                "org_avg": 3.5
            }
        }

        # 5. DB 저장
        result_query = await db.execute(select(DiagnosisResult).where(DiagnosisResult.session_id == session_id))
        existing_result = result_query.scalars().first()
        session_record = await db.get(DiagnosisSession, session_id)

        final_summary = {**analysis_data.get("summary", {}), "details": analysis_data.get("details", {})}

        if existing_result:
            existing_result.total_score = my_avg
            existing_result.scores = analysis_data["scores"]
            existing_result.summary = final_summary
            existing_result.chart_data = chart_data
            result_record = existing_result
        else:
            result_record = DiagnosisResult(
                session_id=session_id,
                participant_id=session_record.user_id,
                total_score=my_avg,
                scores=analysis_data["scores"],
                summary=final_summary,
                chart_data=chart_data
            )
            db.add(result_record)
        
        await db.commit()
        await db.refresh(result_record)
        return result_record