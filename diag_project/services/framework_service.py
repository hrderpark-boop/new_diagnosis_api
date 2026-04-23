from functools import lru_cache

from diag_project.data.competencies import COMPETENCY_FRAMEWORK
from diag_project.schemas.framework import (
    CompetencyOut,
    FrameworkResponse,
    IndicatorOut,
    ScoringInfo,
    TopicOut,
    TopicsResponse,
)

_FRAMEWORK_ID = "leadership_v1"
_SCORING = ScoringInfo(levels=[1, 2, 3, 4], max_score=5.0, methodology="STAR_BEI")


@lru_cache(maxsize=1)
def get_active_framework() -> FrameworkResponse:
    competencies = [
        CompetencyOut(
            key=key,
            name=data["name"],
            order=order,
            description=data["description"],
            classification_keywords=data["classification_keywords"],
            indicators=[
                IndicatorOut(
                    key=ind_key,
                    name=ind["name"],
                    levels={str(lvl): text for lvl, text in ind["levels"].items()},
                    examples={str(lvl): text for lvl, text in ind["examples"].items()},
                )
                for ind_key, ind in data["indicators"].items()
            ],
        )
        for order, (key, data) in enumerate(COMPETENCY_FRAMEWORK.items(), start=1)
    ]
    return FrameworkResponse(
        framework_id=_FRAMEWORK_ID,
        name="리더십 역량진단",
        version="1.0",
        scoring=_SCORING,
        competencies=competencies,
    )


@lru_cache(maxsize=1)
def get_topics() -> TopicsResponse:
    fw = get_active_framework()
    topics = [
        TopicOut(key=c.key, name=c.name, order=c.order)
        for c in fw.competencies
    ]
    return TopicsResponse(
        framework_id=_FRAMEWORK_ID,
        topics=topics,
        total_count=len(topics),
    )
