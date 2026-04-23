from __future__ import annotations
from typing import Dict, List
from pydantic import BaseModel


class ScoringInfo(BaseModel):
    levels: List[int]
    max_score: float
    methodology: str


class IndicatorOut(BaseModel):
    key: str
    name: str
    levels: Dict[str, str]
    examples: Dict[str, str]


class CompetencyOut(BaseModel):
    key: str
    name: str
    order: int
    description: str
    classification_keywords: List[str]
    indicators: List[IndicatorOut]


class FrameworkResponse(BaseModel):
    framework_id: str
    name: str
    version: str
    scoring: ScoringInfo
    competencies: List[CompetencyOut]


class TopicOut(BaseModel):
    key: str
    name: str
    order: int


class TopicsResponse(BaseModel):
    framework_id: str
    topics: List[TopicOut]
    total_count: int
