from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import SecretStr

from app.adapters.route.providers import ProviderSettings, RouteQuery, TMAPAdapter
from app.adapters.route.quota import MAX_PAUSE_SECONDS, CallBudget
from app.adapters.route.service import LiveRouteProvider
from app.adapters.route.transport import HttpReply, _retry_after
from app.modules.engine.schemas import PublicPlaceRef, TransientPlaceDetails
from tests.unit.engine.test_route_providers import MockTransport


def _place(place_id: str, lat: float, lng: float) -> TransientPlaceDetails:
    return TransientPlaceDetails(place_ref=PublicPlaceRef(place_id=place_id), lat=lat, lng=lng)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("3601", MAX_PAUSE_SECONDS),
        ("999999999", MAX_PAUSE_SECONDS),
        ("-1", None),
        ("nan", None),
        ("not-a-delay", None),
        ("0", 0),
        ("Wed, 01 Jan 2098 00:00:00 GMT", MAX_PAUSE_SECONDS),
    ],
)
def test_retry_after_is_bounded_and_invalid_values_are_ignored(value: str, expected: float | None) -> None:
    assert _retry_after(value) == expected


def test_call_budget_caps_pause_even_for_custom_transports() -> None:
    ticks = [0.0]
    budget = CallBudget(10, clock=lambda: ticks[0])
    budget.pause(MAX_PAUSE_SECONDS * 100)

    ticks[0] = MAX_PAUSE_SECONDS - 0.1
    assert not budget.allow()
    ticks[0] = MAX_PAUSE_SECONDS
    assert budget.allow()


@pytest.mark.parametrize(
    ("departure", "expected"),
    [
        (datetime(2026, 11, 8, 15, 30, tzinfo=UTC), "2026-11-09T00:30:00+0900"),
        (
            datetime(2026, 11, 8, 23, 30, tzinfo=timezone(timedelta(hours=-5))),
            "2026-11-09T13:30:00+0900",
        ),
    ],
)
def test_tmap_car_prediction_converts_aware_departure_to_seoul(departure: datetime, expected: str) -> None:
    seen: list[str] = []

    def validate(url, headers, body, encoding, timeout):
        del url, headers, encoding, timeout
        seen.append(body["routesInfo"]["predictionTime"])

    transport = MockTransport(
        [HttpReply(200, {"features": [{"properties": {"totalTime": 600}}]})],
        [validate],
    )
    adapter = TMAPAdapter(
        transport,
        ProviderSettings(api_key=SecretStr("synthetic-key")),
        CallBudget(1),
        clock=lambda: datetime(2026, 11, 8, tzinfo=UTC),
    )
    query = RouteQuery(
        origin=_place("a", 35.1, 129.1),
        destination=_place("b", 35.2, 129.2),
        mode="CAR",
        departure_at=departure,
    )

    result = adapter.lookup(query)

    assert result.duration_min == 10
    assert seen == [expected]


@pytest.mark.parametrize("delay", [-1, float("nan"), float("inf")])
def test_invalid_custom_retry_after_uses_bounded_default_without_retry(delay):
    ticks = [0.0]
    budget = CallBudget(10, clock=lambda: ticks[0])
    transport = MockTransport([HttpReply(429, {}, retry_after=delay)])
    adapter = TMAPAdapter(transport, ProviderSettings(SecretStr("synthetic-key")), budget)
    result = LiveRouteProvider(adapter).estimate(_place("a", 35.1, 129.1), _place("b", 35.2, 129.2), mode="TRANSIT")
    assert result.source == "UNKNOWN" and result.duration_min is None and result.lookup_failed
    assert len(transport.calls) == 1
    ticks[0] = 59.9
    assert not budget.allow()
    ticks[0] = 60
    assert budget.allow()
