"""API-016 블록 시각별 예보(FR-013). 응답은 `Cache-Control: no-store`.

저장된 일정을 다시 계산하지 않고(경로 조회 없음) 공공 장소 블록의 도착 시각 예보만 붙인다. 카카오 장소는 GET 에
좌표가 없어 예보를 붙이지 않는다. 예보가 없거나 조회에 실패한 블록은 빠진다(화면 '예보 없음', ERR-012).
"""

from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response

from app.modules.engine.schemas import ContractModel
from app.modules.places.samples import SamplePlaceData
from app.modules.trips.router import Service as TripServiceDep
from app.modules.trips.router import TripAPIError, translate_error
from app.modules.weather.service import Forecast, WeatherService

router = APIRouter(tags=["weather"])

# 해안 강풍 경고 대상(SRS FR-013 '해수욕장·해안 산책로'). 이름에 이 말이 들어간 실외 장소(잠정).
COAST_WORDS = ("해수욕장", "해변", "해안", "스카이워크", "등대", "바다")


class ForecastOut(ContractModel):
    scope: Literal["SHORT", "MID"]
    pop: int | None
    pty: str | None
    sky: str | None
    temp: float | None
    wind: float | None
    temp_min: float | None = None
    temp_max: float | None = None
    rain: bool = False
    issued_at: datetime


class BlockForecastOut(ContractModel):
    block_id: str
    forecast: ForecastOut
    issued_at: datetime
    scope: Literal["SHORT", "MID"]
    # 실외 장소인가(공공 데이터 실내/실외 속성). 모르면 None.
    outdoor: bool | None
    warnings: tuple[str, ...] = ()


class TripWeatherResponse(ContractModel):
    blocks: tuple[BlockForecastOut, ...] = ()
    # 출처 표기(NFR-007).
    source: str = "기상청 단기예보·중기예보"


def weather_service(request: Request) -> WeatherService:
    service = getattr(request.app.state, "weather_service", None)
    if not isinstance(service, WeatherService):
        raise TripAPIError(503, "ERR-012", "예보를 확인할 수 없어요.")
    return service


def place_data(request: Request) -> SamplePlaceData | None:
    places = getattr(request.app.state, "places", None)
    return places if isinstance(places, SamplePlaceData) else None


def outdoor_of(places: SamplePlaceData | None, place_id: str) -> bool | None:
    item = places.place(place_id) if places is not None else None
    if item is None or not item.indoor_outdoor:
        return None
    return item.indoor_outdoor != "실내"


@router.get("/trips/{trip_id}/weather", response_model=TripWeatherResponse)
def trip_weather(
    trip_id: str,
    response: Response,
    trips: TripServiceDep,
    weather: Annotated[WeatherService, Depends(weather_service)],
    places: Annotated[SamplePlaceData | None, Depends(place_data)],
) -> TripWeatherResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        detail = trips.detail(trip_id)
    except Exception as exc:
        raise translate_error(exc) from None
    start = detail.trip.dates.start
    rows: list[BlockForecastOut] = []
    for day in detail.schedule.days:
        on = start + timedelta(days=day.day_no - 1)
        for block in day.blocks:
            place = block.place
            if getattr(place, "source", None) != "PUBLIC" or block.arrive_at is None:
                continue
            try:
                found: Forecast | None = weather.forecast(place.lat, place.lng, on, block.arrive_at.hour)  # type: ignore[union-attr]
            except Exception:
                found = None  # 예보 없음(ERR-012). 다른 블록은 계속 붙인다.
            if found is None:
                continue
            outdoor = outdoor_of(places, place.id)  # type: ignore[union-attr]
            warnings: list[str] = []
            name = getattr(place, "name", "")
            if (
                outdoor
                and found.wind is not None
                and found.wind >= weather.settings.coast_wind_ms
                and any(word in name for word in COAST_WORDS)
            ):
                warnings.append(f"바닷가 바람이 강해요(초속 {found.wind:g}m)")
            if outdoor and found.rain:
                warnings.append("실외 장소인데 비 예보가 있어요")
            rows.append(
                BlockForecastOut(
                    block_id=block.id,
                    forecast=ForecastOut(
                        scope=found.scope,
                        pop=found.pop,
                        pty=found.pty,
                        sky=found.sky,
                        temp=found.temp,
                        wind=found.wind,
                        temp_min=found.temp_min,
                        temp_max=found.temp_max,
                        rain=found.rain,
                        issued_at=found.issued_at,
                    ),
                    issued_at=found.issued_at,
                    scope=found.scope,
                    outdoor=outdoor,
                    warnings=tuple(warnings),
                )
            )
    return TripWeatherResponse(blocks=tuple(rows))
