# diag_project/routes/competency_routes.py

from fastapi import APIRouter, HTTPException, status
from typing import List, Optional
import uuid 

router = APIRouter(
    prefix="/api/v1/competency-routes", # ⚠️ 경로 충돌 방지를 위해 prefix 변경
    tags=["Competencies (Static Data)"], 
)

# competencies.py 파일에서 COMPETENCY_FRAMEWORK 불러오기
from diag_project.data.competencies import COMPETENCY_FRAMEWORK
# ⚠️ 수정된 schemas.competency에서 스키마 임포트
from diag_project.schemas.competency import (
    CompetencySummary,
    CompetenciesListResponse,
    CompetencyDetail,
    IndicatorDetail,
    IndicatorLevel 
)

@router.get(
    "", 
    response_model=CompetenciesListResponse,
    summary="[Static] 모든 역량 목록 조회",
    description="정의된 모든 리더십 역량의 요약 정보를 반환합니다."
)
async def get_all_competencies():
    competencies_summary_list: List[CompetencySummary] = []
    for comp_id, comp_data in COMPETENCY_FRAMEWORK.items():
        competencies_summary_list.append(
            CompetencySummary(
                id=comp_id, 
                name=comp_data["name"],
                description=comp_data["description"]
            )
        )
    
    return CompetenciesListResponse(
        items=competencies_summary_list,
        total=len(competencies_summary_list),
        skip=0,
        limit=len(competencies_summary_list)
    )

@router.get(
    "/{competency_id}", 
    response_model=CompetencyDetail, 
    summary="[Static] 특정 역량 상세 정보 조회",
    description="제공된 역량 ID에 해당하는 역량의 상세 정보를 반환합니다."
)
async def get_competency_detail(competency_id: str):
    comp_data = COMPETENCY_FRAMEWORK.get(competency_id)

    if not comp_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Competency not found")

    indicators_detail_list: List[IndicatorDetail] = []
    for ind_id, ind_data in comp_data["indicators"].items():
        levels_list: List[IndicatorLevel] = []
        for level_num, level_desc in ind_data["levels"].items():
            example_text = ind_data.get("examples", {}).get(level_num) 
            levels_list.append(
                IndicatorLevel(
                    level=level_num,
                    description=level_desc,
                    examples=example_text 
                )
            )
        indicators_detail_list.append(
            IndicatorDetail(
                id=ind_id,
                competency_id=competency_id, 
                name=ind_data["name"],
                description=ind_data.get("description"), 
                levels=levels_list 
            )
        )

    return CompetencyDetail(
        id=competency_id,
        name=comp_data["name"],
        description=comp_data["description"],
        indicators=indicators_detail_list
    )