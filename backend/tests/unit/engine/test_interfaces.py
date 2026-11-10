from datetime import UTC, date, datetime

from app.modules.engine.interfaces import (
    PlaceDataProvider,
    RouteEstimate,
    RouteProvider,
)
from app.modules.engine.schemas import PlaceRef, PublicPlaceRef, TransientPlaceDetails


class FakePlaceDataProvider:
    def get(self, place_ref: PlaceRef, *, on_date: date) -> TransientPlaceDetails:
        del on_date
        return TransientPlaceDetails(
            place_ref=place_ref,
            name="테스트 전용 장소",
            lat=35.0,
            lng=129.0,
        )


class FakeRouteProvider:
    def estimate(
        self,
        origin: TransientPlaceDetails,
        destination: TransientPlaceDetails,
        *,
        mode: str,
    ) -> RouteEstimate:
        del origin, destination, mode
        return RouteEstimate(
            duration_min=15,
            source="ESTIMATED",
            computed_at=datetime(2026, 11, 2, tzinfo=UTC),
        )


def test_place_and_route_dependencies_accept_test_fakes() -> None:
    place_provider = FakePlaceDataProvider()
    route_provider = FakeRouteProvider()
    assert isinstance(place_provider, PlaceDataProvider)
    assert isinstance(route_provider, RouteProvider)

    origin = place_provider.get(PublicPlaceRef(place_id="origin"), on_date=date(2026, 11, 2))
    destination = place_provider.get(PublicPlaceRef(place_id="destination"), on_date=date(2026, 11, 2))
    estimate = route_provider.estimate(origin, destination, mode="TRANSIT")

    assert estimate.duration_min == 15
    assert estimate.source == "ESTIMATED"
