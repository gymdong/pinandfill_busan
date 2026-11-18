"""API-005 장소 상세. 공공 DB 장소만 다룬다(카카오 장소는 상세가 없어 404).

places·place_hours·place_photos 테이블이 생기기 전에는 data/samples 표본으로 응답한다.
테이블이 들어오면 `PlaceDetailProvider` 구현만 바꿔 주입한다.
"""

from typing import Protocol

from .api_schemas import DayType, IndoorOutdoor, PlaceDetailHours, PlaceDetailPlace, PlaceDetailResponse, SourceInfo
from .samples import SamplePlaceData

# 표본 영업시간은 요일(MON~SUN)만 있다. 공휴일(HOLIDAY) 행은 아직 읽지 않는다.
WEEK: tuple[DayType, ...] = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
# 표본 CSV 는 '실외'를 쓰고 SDD·프런트는 '야외'를 쓴다. 모르는 값은 만들지 않고 null 로 둔다.
INDOOR_OUTDOOR: dict[str, IndoorOutdoor] = {"실내": "실내", "야외": "야외", "실외": "야외", "반야외": "반야외"}


class PlaceNotFoundError(LookupError):
    """공공 DB 에 없는 장소 ID(카카오 장소 ID 포함)."""


class PlaceDetailProvider(Protocol):
    def place_detail(self, place_id: str) -> PlaceDetailResponse | None: ...


class SamplePlaceDetails:
    """data/samples 표본의 장소 상세. 사진·혼잡 데이터는 아직 없어 비워 둔다."""

    def __init__(self, places: SamplePlaceData) -> None:
        self._places = places

    def place_detail(self, place_id: str) -> PlaceDetailResponse | None:
        item = self._places.place(place_id)
        if item is None:
            return None
        place = item.place
        hours = tuple(
            PlaceDetailHours(
                day_type=day_type,
                open_time=value.open_time,
                close_time=value.close_time,
                break_start=value.break_start,
                break_end=value.break_end,
                is_closed=value.is_closed,
            )
            for day_type in WEEK
            if (value := item.hours.get(day_type)) is not None
        )
        sources = (
            (SourceInfo(org=item.source_org, ref_date=item.ref_date),) if item.source_org and item.ref_date else ()
        )
        return PlaceDetailResponse(
            place=PlaceDetailPlace(
                id=place.id,
                name=place.name,
                lat=place.lat,
                lng=place.lng,
                category=place.category,
                closed_days_text=item.closed_days_text,
                default_stay_min=item.stay_min,
                indoor_outdoor=INDOOR_OUTDOOR.get(item.indoor_outdoor or ""),
                ref_date=item.ref_date,
            ),
            hours=hours,
            sources=sources,
        )


class PlaceDetailService:
    def __init__(self, provider: PlaceDetailProvider) -> None:
        self._provider = provider

    def get(self, place_id: str) -> PlaceDetailResponse:
        detail = self._provider.place_detail(place_id)
        if detail is None:
            raise PlaceNotFoundError
        return detail
