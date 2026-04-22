# diag_project/routes/coaches.py

import uuid
from typing import List
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["Coaches"])

# 응답 모델 정의
class CoachResponse(BaseModel):
    id: str # UUID를 문자열로 처리
    name: str
    description: str
    avatar_url: str
    character_tags: List[str]

# 백엔드 서버 주소 (이미지 서빙용)
BASE_URL = "http://127.0.0.1:8000"

@router.get("", response_model=List[CoachResponse])
async def get_coaches():
    """
    6명의 정예 AI 코치 목록 반환 (.png 버전)
    """
    return [
        {
            "id": "10000000-0000-0000-0000-000000000011",
            "name": "Ella (엘라)",
            "description": "당신의 이야기를 깊이 있게 들어주는\n따뜻한 멘토입니다.",
            "avatar_url": f"{BASE_URL}/coaches/female1.png",
            "character_tags": ["#따뜻함", "#공감", "#경청", "#힐링"]
        },
        {
            "id": "10000000-0000-0000-0000-000000000012",
            "name": "Jessica (제시카)",
            "description": "데이터와 논리로 당신의 성장을 돕는\n냉철한 전략가입니다.",
            "avatar_url": f"{BASE_URL}/coaches/female2.png",
            "character_tags": ["#냉철함", "#분석적", "#직설적", "#성장"]
        },
        {
            "id": "10000000-0000-0000-0000-000000000013",
            "name": "Olivia (올리비아)",
            "description": "틀에 박히지 않은 시각으로\n당신의 잠재력을 깨워줍니다.",
            "avatar_url": f"{BASE_URL}/coaches/female3.png",
            "character_tags": ["#창의적", "#자유로움", "#영감", "#비전"]
        },
        {
            "id": "10000000-0000-0000-0000-000000000014",
            "name": "Daniel (다니엘)",
            "description": "풍부한 경험을 바탕으로 든든하게 이끌어주는\n선배 같은 코치입니다.",
            "avatar_url": f"{BASE_URL}/coaches/male1.png",
            "character_tags": ["#신뢰", "#든든함", "#경험", "#리더십"]
        },
        {
            "id": "10000000-0000-0000-0000-000000000015",
            "name": "Michael (마이클)",
            "description": "지치지 않는 열정으로\n당신에게 에너지를 불어넣습니다.",
            "avatar_url": f"{BASE_URL}/coaches/male2.png",
            "character_tags": ["#열정", "#동기부여", "#에너지", "#파이팅"]
        },
        {
            "id": "10000000-0000-0000-0000-000000000016",
            "name": "Lucas (루카스)",
            "description": "군더더기 없이 핵심을 찌르는\n스마트한 솔루션 메이커입니다.",
            "avatar_url": f"{BASE_URL}/coaches/male3.png",
            "character_tags": ["#스마트", "#효율", "#핵심", "#솔루션"]
        }
    ]