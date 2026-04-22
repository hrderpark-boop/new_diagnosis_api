# diag_project/routes/group.py

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from diag_project.database import get_db
# [THE FIX] 서비스 모듈을 직접 임포트 (services/__init__.py가 비어있어도 작동함)
from diag_project.services import group as group_service

# [THE FIX] 스키마는 schemas 패키지에서 임포트
from diag_project.schemas.group import (
    GroupCreate,
    GroupUpdate,
    GroupResponse,
    GroupListResponse,
)

router = APIRouter(
    prefix="/api/v1/groups",
    tags=["Groups"],
    responses={404: {"description": "Not found"}},
)

@router.post("/", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group_api(group: GroupCreate, db: AsyncSession = Depends(get_db)):
    """
    새로운 그룹을 생성합니다.
    """
    # 중복 체크
    existing_group = await group_service.get_group_by_code(db, group.group_code)
    if existing_group:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Group with code '{group.group_code}' already exists"
        )
    
    db_group = await group_service.create_group(db=db, group=group)
    return db_group

@router.get("/", response_model=GroupListResponse)
async def read_groups_api(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    """
    모든 그룹 목록을 조회합니다.
    """
    groups, total_count = await group_service.get_groups(db=db, skip=skip, limit=limit)
    return GroupListResponse(items=groups, total=total_count, skip=skip, limit=limit)

@router.get("/{group_id}", response_model=GroupResponse)
async def read_group_api(group_id: str, db: AsyncSession = Depends(get_db)):
    """
    ID로 특정 그룹을 조회합니다.
    """
    try:
        validated_uuid = UUID(group_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID format")
        
    db_group = await group_service.get_group(db=db, group_id=validated_uuid)
    if db_group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return db_group

@router.patch("/{group_id}", response_model=GroupResponse)
async def update_group_api(group_id: str, group_update: GroupUpdate, db: AsyncSession = Depends(get_db)):
    """
    ID로 특정 그룹을 업데이트합니다.
    """
    try:
        validated_uuid = UUID(group_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID format")

    existing_group = await group_service.get_group(db=db, group_id=validated_uuid)
    if existing_group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    if group_update.group_code is not None and group_update.group_code != existing_group.group_code:
        duplicate_group = await group_service.get_group_by_code(db, group_update.group_code)
        if duplicate_group and duplicate_group.id != validated_uuid: 
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Group with code '{group_update.group_code}' already exists"
            )
    updated_group = await group_service.update_group(db=db, group_id=validated_uuid, group_update=group_update)
    return updated_group

@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group_api(group_id: str, db: AsyncSession = Depends(get_db)):
    """
    ID로 특정 그룹을 삭제합니다.
    """
    try:
        validated_uuid = UUID(group_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID format")
        
    db_group = await group_service.get_group(db=db, group_id=validated_uuid)
    if db_group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    await group_service.delete_group(db=db, group_id=validated_uuid)
    return Response(status_code=status.HTTP_204_NO_CONTENT)