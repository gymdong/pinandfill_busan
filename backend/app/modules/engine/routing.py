"""One boundary for Busan trip dates and optional departure-aware providers."""

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.modules.engine.interfaces import DepartureAwareRouteProvider, RouteEstimate, RouteProvider
from app.modules.engine.schemas import StoredBlock, TransientPlaceDetails, TripWindow

try:
    _SEOUL: ZoneInfo | None = ZoneInfo("Asia/Seoul")
except ZoneInfoNotFoundError:
    _SEOUL = None


def seoul_datetime(day: date, value: time) -> datetime | None:
    if _SEOUL is not None:
        return datetime.combine(day, value, tzinfo=_SEOUL)
    # Windows may lack IANA tzdata. Modern Seoul has UTC+09 with no DST since
    # 1988; do not pretend this bounded fallback handles historical transitions.
    if day < date(1989, 1, 1):
        return None
    return datetime.combine(day, value, tzinfo=timezone(timedelta(hours=9), "Asia/Seoul"))


def departure_for(trip: TripWindow, block: StoredBlock) -> datetime | None:
    if block.depart_at is None:
        return None
    day = trip.start_date + timedelta(days=block.day_no - 1)
    return seoul_datetime(day, block.depart_at)


def estimate_departing(
    provider: RouteProvider,
    origin: TransientPlaceDetails,
    destination: TransientPlaceDetails,
    *,
    mode: Literal["TRANSIT", "CAR", "WALK"],
    departure_at: datetime,
) -> RouteEstimate:
    if isinstance(provider, DepartureAwareRouteProvider):
        return provider.estimate_at(origin, destination, mode=mode, departure_at=departure_at)
    # Compatibility for existing time-independent Fake providers, not a claim
    # that a legacy provider predicts traffic at the requested time.
    return provider.estimate(origin, destination, mode=mode)
