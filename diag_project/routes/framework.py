from fastapi import APIRouter

from diag_project.schemas.framework import FrameworkResponse, TopicsResponse
from diag_project.services.framework_service import get_active_framework, get_topics

router = APIRouter(tags=["framework"])


@router.get("", response_model=FrameworkResponse)
async def read_framework() -> FrameworkResponse:
    return get_active_framework()


@router.get("/topics", response_model=TopicsResponse)
async def read_topics() -> TopicsResponse:
    return get_topics()
