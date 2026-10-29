"""교육과정 Pool(공급원) 단일 입구.

맞춤 교육체계도는 과정을 여기서만 꺼낸다. 지금은 data/course_matrix.py 의 카탈로그(26 하위역량 × A~D)가 Pool 이다.
나중에 협의해 확정한 Pool(DB·엑셀 관리 등)로 바꿀 때 이 파일의 get_course / tracks 만 바꾸면 체계도 구성 로직은 그대로 쓴다.
"""
from typing import Dict, List, Optional

from diag_project.data.course_matrix import COURSE_CATALOG, TRACK_META


def get_course(comp_key: str, sub_name: str, track: str) -> Optional[Dict[str, str]]:
    """(역량, 하위역량, 트랙) → {course, goal, format}. Pool 에 없으면 None."""
    entry = COURSE_CATALOG.get((comp_key, sub_name))
    if not entry or track not in entry:
        return None
    c = entry[track]
    meta = TRACK_META.get(track, {})
    return {"course": c.get("course"), "goal": c.get("subtitle"), "format": meta.get("format")}


def subs_of(comp_key: str) -> List[str]:
    """Pool 에 있는 그 역량의 하위역량 이름(카탈로그 순서)."""
    return [sub for (k, sub) in COURSE_CATALOG.keys() if k == comp_key]


def tracks() -> List[Dict[str, object]]:
    return [{"track": t, "from_level": m.get("diagnosed_level"), "to_level": m.get("target_level"),
             "format": m.get("format")} for t, m in TRACK_META.items()]
