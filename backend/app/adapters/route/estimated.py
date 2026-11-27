"""경로 API 를 쓸 수 없을 때의 추정 이동시간(SRS 2.1, SDD: TMAP → ODsay → 추정).

직선거리 × 도로 우회 계수를 수단별 평균 속도로 나눈다. 결과는 source="ESTIMATED"(화면 '추정')이고
시간표·교통 예측이 아니므로 time_semantics="static" 이다. 값은 잠정이며 실제 경로 응답과 비교해 조정한다.
좌표가 없으면 추정하지 않는다(이동시간을 지어내지 않는다).
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.adapters.route.providers import utc_now
from app.modules.engine.interfaces import RouteEstimate, RouteProvider
from app.modules.engine.routing import estimate_departing
from app.modules.engine.schemas import TransientPlaceDetails

Mode = Literal["TRANSIT", "CAR", "WALK"]
EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True)
class EstimateParams:
    """수단별 (평균 속도 km/h, 고정 시간 분). 대중교통 고정 시간은 정류장까지 걷기·기다림."""

    road_factor: float = 1.3
    walk_kmh: float = 4.5
    # 2026-11-27 TMAP 응답 두 구간(용두산→광안리 41분, 광안리→시립미술관 21분)에 맞춘 잠정값
    transit_kmh: float = 22.0
    transit_overhead_min: float = 10.0
    car_kmh: float = 25.0
    car_overhead_min: float = 5.0
    # 이 거리(km, 우회 계수 적용 뒤) 이하이면 대중교통 대신 걷는 시간으로 본다.
    transit_walk_km: float = 1.0


DEFAULT_PARAMS = EstimateParams()


def distance_km(origin: TransientPlaceDetails, destination: TransientPlaceDetails) -> float | None:
    if None in (origin.lat, origin.lng, destination.lat, destination.lng):
        return None
    lat1, lng1 = math.radians(origin.lat or 0), math.radians(origin.lng or 0)
    lat2, lng2 = math.radians(destination.lat or 0), math.radians(destination.lng or 0)
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def estimate_minutes(km: float, mode: Mode, params: EstimateParams = DEFAULT_PARAMS) -> int:
    road = km * params.road_factor
    walk = road / params.walk_kmh * 60
    if mode == "WALK" or (mode == "TRANSIT" and road <= params.transit_walk_km):
        minutes = walk
    elif mode == "TRANSIT":
        minutes = min(walk, params.transit_overhead_min + road / params.transit_kmh * 60)
    else:
        minutes = params.car_overhead_min + road / params.car_kmh * 60
    return max(1, math.ceil(minutes))


class EstimatedFallbackRouteProvider:
    """먼저 실제 경로(inner)를 묻고, 이동시간을 못 받으면 추정값을 쓴다. inner 가 없으면 추정만 한다."""

    def __init__(
        self,
        inner: RouteProvider | None,
        *,
        params: EstimateParams = DEFAULT_PARAMS,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.inner = inner
        self.params = params
        self.clock = clock

    def _fallback(
        self, origin: TransientPlaceDetails, destination: TransientPlaceDetails, mode: Mode, real: RouteEstimate | None
    ) -> RouteEstimate:
        if real is not None and real.duration_min is not None and not real.lookup_failed:
            return real
        km = distance_km(origin, destination)
        if km is None:
            return real if real is not None else RouteEstimate(None, "UNKNOWN", self.clock(), lookup_failed=True)
        return RouteEstimate(
            estimate_minutes(km, mode, self.params), "ESTIMATED", self.clock(), time_semantics="static"
        )

    def estimate(
        self, origin: TransientPlaceDetails, destination: TransientPlaceDetails, *, mode: Mode
    ) -> RouteEstimate:
        real = self.inner.estimate(origin, destination, mode=mode) if self.inner is not None else None
        return self._fallback(origin, destination, mode, real)

    def estimate_at(
        self,
        origin: TransientPlaceDetails,
        destination: TransientPlaceDetails,
        *,
        mode: Mode,
        departure_at: datetime,
    ) -> RouteEstimate:
        real = (
            estimate_departing(self.inner, origin, destination, mode=mode, departure_at=departure_at)
            if self.inner is not None
            else None
        )
        return self._fallback(origin, destination, mode, real)
