"""API-003·API-005 응답 형식. 프런트 `frontend/src/types/api.ts` 와 필드가 같다."""

from datetime import date
from typing import Literal

from pydantic import Field

from app.modules.engine.schemas import ContractModel, LocalTime

from .schemas import HoursStatus, PlaceBadge


class Coords(ContractModel):
    lat: float = Field(repr=False)
    lng: float = Field(repr=False)


class PlaceSearchItem(ContractModel):
    """검색 결과 1건. 이름·좌표·주소는 카카오 응답 값이라 응답으로만 내보내고 저장하지 않는다(D6)."""

    # 공공 DB 와 매칭되면 places.id, 아니면 null
    place_id: str | None
    kakao_place_id: str
    # 블록 추가(API-006)에 그대로 쓸 수 있는 표준 형식
    place_url: str
    name: str = Field(repr=False)
    coords: Coords
    category: str | None
    address: str | None = Field(repr=False)
    badge: PlaceBadge
    hours_status: HoursStatus


class PlaceSearchResponse(ContractModel):
    places: tuple[PlaceSearchItem, ...] = ()


class PlacesAtResponse(ContractModel):
    """API-004. 프런트 `PlacesAtResponse` 와 같다."""

    places: tuple[PlaceSearchItem, ...] = ()
    nearby_count: int = Field(0, ge=0)


# ---------- API-005 장소 상세. 프런트 `PlaceDetailResponse`(frontend/src/types/api.ts)와 필드가 같다. ----------

DayType = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN", "HOLIDAY"]
IndoorOutdoor = Literal["실내", "야외", "반야외"]


class PlaceDetailPlace(ContractModel):
    """공공 DB 장소(SDD 5.2 places). 공공 데이터라 이름·좌표를 응답에 그대로 싣는다."""

    id: str
    name: str
    lat: float
    lng: float
    category: str
    source: Literal["PUBLIC"] = "PUBLIC"
    # 표본·DB 에 없는 값은 만들지 않고 null 이다(NFR-012).
    description: str | None = None
    closed_days_text: str | None = None
    default_stay_min: int | None = None
    indoor_outdoor: IndoorOutdoor | None = None
    rating: float | None = None
    ref_date: date | None = None


class PlaceDetailHours(ContractModel):
    """요일별 영업시간. 시각이 null 이면 '확인 필요'다."""

    day_type: DayType
    open_time: LocalTime | None = None
    close_time: LocalTime | None = None
    break_start: LocalTime | None = None
    break_end: LocalTime | None = None
    is_closed: bool = False


class PlaceDetailPhoto(ContractModel):
    id: str
    url: str
    source_org: str
    # null 이면 '저작권 유형 확인 필요'
    license_type: str | None = None
    is_primary: bool = False


class SourceInfo(ContractModel):
    org: str
    # null 이면 기준일 정보가 없다. 기관명은 그대로 보여 주고 기준일만 '확인 필요'로 둔다(NFR-007·012).
    ref_date: date | None = None


class PlaceDetailResponse(ContractModel):
    place: PlaceDetailPlace
    hours: tuple[PlaceDetailHours, ...] = ()
    # 대표 사진이 앞이다. 사진이 없으면 비어 있고 다른 출처 사진으로 채우지 않는다(FR-014).
    photos: tuple[PlaceDetailPhoto, ...] = ()
    # 날씨는 P1(FR-013)이라 null 이다.
    weather: None = None
    # 혼잡 요약은 혼잡 모듈(홍민지)이 들어오면 붙인다. 그 전에는 null('정보 부족')이다.
    crowd: None = None
    sources: tuple[SourceInfo, ...] = ()
