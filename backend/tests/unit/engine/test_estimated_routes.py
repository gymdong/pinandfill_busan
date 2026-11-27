"""추정 이동시간(경로 API 를 못 쓸 때, SRS 2.1)."""

from datetime import UTC, datetime

from app.adapters.route.estimated import EstimatedFallbackRouteProvider, distance_km, estimate_minutes
from app.modules.engine.interfaces import RouteEstimate
from app.modules.engine.schemas import PublicPlaceRef, TransientPlaceDetails

DEPARTURE = datetime(2026, 12, 5, 11, tzinfo=UTC)
# 용두산 공원 → 광안리해수욕장(직선 약 9km)
A = TransientPlaceDetails(place_ref=PublicPlaceRef(place_id="a"), lat=35.1007, lng=129.0326)
B = TransientPlaceDetails(place_ref=PublicPlaceRef(place_id="b"), lat=35.1532, lng=129.1186)
NO_COORDS = TransientPlaceDetails(place_ref=PublicPlaceRef(place_id="c"))


class Fixed:
    def __init__(self, estimate: RouteEstimate) -> None:
        self.value = estimate
        self.calls = 0

    def estimate(self, origin: object, destination: object, *, mode: str) -> RouteEstimate:
        self.calls += 1
        return self.value


def test_distance_and_minutes_by_mode() -> None:
    km = distance_km(A, B)
    assert km is not None and 9 < km < 10.5
    assert estimate_minutes(km, "WALK") > estimate_minutes(km, "TRANSIT") > estimate_minutes(km, "CAR")
    # 아주 가까우면 대중교통도 걷는 시간이다
    assert estimate_minutes(0.3, "TRANSIT") == estimate_minutes(0.3, "WALK")
    assert estimate_minutes(0, "CAR") >= 1


def test_real_duration_is_kept() -> None:
    real = RouteEstimate(41, "TMAP", DEPARTURE)
    assert EstimatedFallbackRouteProvider(Fixed(real)).estimate_at(A, B, mode="TRANSIT", departure_at=DEPARTURE) == real


def test_failed_lookup_is_estimated_and_labelled() -> None:
    failed = RouteEstimate(None, "UNKNOWN", DEPARTURE, lookup_failed=True)
    result = EstimatedFallbackRouteProvider(Fixed(failed), clock=lambda: DEPARTURE).estimate(A, B, mode="TRANSIT")
    assert result.source == "ESTIMATED" and result.time_semantics == "static" and not result.lookup_failed
    assert result.duration_min is not None and 20 <= result.duration_min <= 60


def test_without_coordinates_nothing_is_invented() -> None:
    result = EstimatedFallbackRouteProvider(None).estimate(A, NO_COORDS, mode="TRANSIT")
    assert result.duration_min is None and result.source == "UNKNOWN"
