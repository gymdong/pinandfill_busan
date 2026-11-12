from datetime import time
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PlaceHours(BaseModel):
    """공공 DB 영업시간 한 행(SDD 5.2 place_hours). 시각이 비어 있으면 '확인 필요'다."""

    model_config = ConfigDict(frozen=True)

    day_type: str
    open_time: time | None = None
    close_time: time | None = None
    is_closed: bool = False


class PublicPlace(BaseModel):
    """공공 DB 장소(SDD 5.2 places) 중 검색·매칭에 쓰는 필드."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    category: str
    hours: tuple[PlaceHours, ...] = ()


class PlaceBadge(StrEnum):
    """DETAIL 은 '상세 정보 있음', BASIC 은 '기본 정보만'이다."""

    DETAIL = "DETAIL"
    BASIC = "BASIC"


class HoursStatus(StrEnum):
    """NEEDS_CHECK 는 영업시간 '확인 필요'다."""

    KNOWN = "KNOWN"
    NEEDS_CHECK = "NEEDS_CHECK"
