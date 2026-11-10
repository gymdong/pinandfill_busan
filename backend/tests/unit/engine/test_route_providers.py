import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Literal, cast

import pytest
from pydantic import SecretStr

from app.adapters.route.providers import ODsayAdapter, ProviderSettings, RouteQuery, TMAPAdapter
from app.adapters.route.quota import CallBudget
from app.adapters.route.service import LiveRouteProvider
from app.adapters.route.transport import HttpReply, SafeHTTPTransport, TransportError
from app.modules.engine.schemas import PublicPlaceRef, TransientPlaceDetails
from tests.unit.engine.test_route_transport import FakeConnection, FakeResponse

NOW = datetime(2026, 11, 8, 3, tzinfo=UTC)
KST = timezone(timedelta(hours=9))


class MockTransport:
    """Response queue that retains endpoint labels only, never keys or coordinates."""

    def __init__(
        self,
        replies: list[HttpReply | Exception],
        validators: list[Callable[[str, dict[str, str], dict[str, Any], str, float], None]] | None = None,
    ) -> None:
        self.replies = list(replies)
        self.validators = list(validators or [])
        self.calls: list[str] = []

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any],
        encoding: Literal["json", "form"],
        timeout: float,
    ) -> HttpReply:
        self.calls.append(url.split("/")[3])
        if self.validators:
            self.validators.pop(0)(url, headers, body, encoding, timeout)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def __repr__(self) -> str:
        return f"MockTransport(calls={self.calls!r})"


def place(place_id: str, *, lat: float | None = 35.1, lng: float | None = 129.1) -> TransientPlaceDetails:
    return TransientPlaceDetails(place_ref=PublicPlaceRef(place_id=place_id), lat=lat, lng=lng)


def query(mode: Literal["TRANSIT", "CAR", "WALK"] = "TRANSIT", *, departure: datetime | None = None) -> RouteQuery:
    return RouteQuery(origin=place("a"), destination=place("b", lat=35.2, lng=129.2), mode=mode, departure_at=departure)


def settings(key: str = "route-secret-key") -> ProviderSettings:
    return ProviderSettings(SecretStr(key), timeout_seconds=2.5)


def tmap(transport: MockTransport, *, limit: int = 100) -> TMAPAdapter:
    return TMAPAdapter(transport, settings(), CallBudget(limit), clock=lambda: NOW)


def odsay(transport: MockTransport, *, limit: int = 100) -> ODsayAdapter:
    return ODsayAdapter(transport, settings(), CallBudget(limit), search_timezone=KST, clock=lambda: NOW)


@pytest.mark.parametrize(
    ("mode", "payload", "expected"),
    [
        (
            "TRANSIT",
            {
                "metaData": {
                    "plan": {
                        "itineraries": [
                            {"totalTime": 1_201, "legs": [{"mode": "BUS", "service": 1}]},
                            {"totalTime": 900, "legs": [{"mode": "BUS", "service": 0}]},
                        ]
                    }
                }
            },
            21,
        ),
        ("CAR", {"features": [{"properties": {"totalTime": 601}}]}, 11),
        ("WALK", {"features": [{"properties": {"totalTime": 600}}]}, 10),
    ],
)
def test_tmap_modes_convert_seconds_and_preserve_source(
    mode: Literal["TRANSIT", "CAR", "WALK"], payload: dict[str, Any], expected: int
) -> None:
    transport = MockTransport([HttpReply(200, payload)])
    result = tmap(transport).lookup(query(mode))
    assert (result.duration_min, result.provider, result.failure, result.computed_at) == (expected, "TMAP", None, NOW)
    assert result.departure_applied is False


def test_tmap_car_prediction_applies_exact_aware_departure_without_place_names() -> None:
    departure = datetime(2026, 11, 8, 12, 34, tzinfo=KST)

    def validate(url: str, headers: dict[str, str], body: dict[str, Any], encoding: str, timeout: float) -> None:
        assert url.endswith("/tmap/routes/prediction?version=1")
        assert headers["appKey"] == "route-secret-key"
        assert (encoding, timeout) == ("json", 2.5)
        info = body["routesInfo"]
        assert info["predictionTime"] == "2026-11-08T12:34:00+0900"
        assert info["departure"]["name"] == "origin"
        assert info["destination"]["name"] == "destination"
        assert "합성" not in repr(body)

    adapter = tmap(MockTransport([HttpReply(200, {"features": [{"properties": {"totalTime": 60}}]})], [validate]))
    result = adapter.lookup(query("CAR", departure=departure))
    assert (result.duration_min, result.departure_applied) == (1, True)


@pytest.mark.parametrize("mode", ["TRANSIT", "WALK"])
def test_tmap_does_not_claim_departure_support_for_transit_or_walk(mode: Literal["TRANSIT", "WALK"]) -> None:
    transport = MockTransport([])
    result = tmap(transport).lookup(query(mode, departure=datetime(2026, 11, 8, 12, tzinfo=KST)))
    assert (result.duration_min, result.failure, transport.calls) == (None, "unsupported_departure", [])


@pytest.mark.parametrize(
    ("payload", "failure"),
    [
        ({}, "invalid_response"),
        ({"features": "bad"}, "invalid_response"),
        ({"features": []}, "no_route"),
        ({"features": [{"properties": {"totalTime": -1}}]}, "no_route"),
        ({"features": [{"properties": {"totalTime": True}}]}, "no_route"),
    ],
)
def test_tmap_rejects_malformed_or_empty_durations(payload: dict[str, Any], failure: str) -> None:
    result = tmap(MockTransport([HttpReply(200, payload)])).lookup(query("CAR"))
    assert (result.duration_min, result.failure) == (None, failure)


@pytest.mark.parametrize(("mode", "path_type"), [("TRANSIT", 2), ("WALK", 1)])
def test_odsay_maas_uses_timezone_and_minute_duration(mode: Literal["TRANSIT", "WALK"], path_type: int) -> None:
    departure = datetime(2026, 11, 8, 3, 4, tzinfo=UTC)

    def validate(url: str, headers: dict[str, str], body: dict[str, Any], encoding: str, timeout: float) -> None:
        assert url == "https://api.odsay.com/v1/api/maasRP"
        assert "appKey" not in headers
        assert body["apiKey"] == "route-secret-key"
        assert body["SearchTime"] == "202611081204"
        assert body["SearchMethod"] == str(path_type)
        assert (encoding, timeout) == ("form", 2.5)

    payload = {"result": {"paths": [{"pathType": path_type, "totalTime": 17}]}}
    result = odsay(MockTransport([HttpReply(200, payload)], [validate])).lookup(query(mode, departure=departure))
    assert (result.duration_min, result.provider, result.failure, result.departure_applied) == (17, "ODSAY", None, True)


def test_odsay_uses_injected_clock_when_departure_is_absent_without_claiming_it_was_applied() -> None:
    seen: list[str] = []

    def validate(url: str, headers: dict[str, str], body: dict[str, Any], encoding: str, timeout: float) -> None:
        del url, headers, encoding, timeout
        seen.append(body["SearchTime"])

    payload = {"result": {"paths": [{"pathType": 2, "totalTime": 25}]}}
    result = odsay(MockTransport([HttpReply(200, payload)], [validate])).lookup(query())
    assert seen == ["202611081200"]
    assert (result.duration_min, result.departure_applied) == (25, False)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {}, "authentication"),
        (403, {}, "authentication"),
        (400, {}, "upstream"),
        (500, {}, "upstream"),
        (200, {"error": [{"code": "500", "message": "[ApiKeyAuthFailed] hidden"}]}, "authentication"),
        (200, {"error": [{"code": "-99", "message": "hidden"}]}, "upstream"),
    ],
)
def test_upstream_status_and_embedded_errors_are_classified(status: int, body: dict[str, Any], expected: str) -> None:
    result = odsay(MockTransport([HttpReply(status, body)])).lookup(query())
    assert (result.duration_min, result.failure) == (None, expected)


@pytest.mark.parametrize(
    ("error", "expected"),
    [("timeout", "timeout"), ("network", "network"), ("invalid_response", "invalid_response")],
)
def test_transport_failures_remain_sanitized(error: str, expected: str) -> None:
    result = tmap(MockTransport([TransportError(cast(Any, error))])).lookup(query())
    assert (result.duration_min, result.failure) == (None, expected)


def test_missing_key_and_budget_exhaustion_never_call_transport() -> None:
    transport = MockTransport([])
    missing = TMAPAdapter(transport, settings(""), CallBudget(1), clock=lambda: NOW).lookup(query())
    limited = tmap(transport, limit=0).lookup(query())
    assert (missing.failure, limited.failure, transport.calls) == ("missing_key", "quota", [])


def test_429_pauses_budget_and_prevents_another_call() -> None:
    ticks = [0.0]
    budget = CallBudget(10, clock=lambda: ticks[0])
    transport = MockTransport([HttpReply(429, {}, retry_after=30)])
    adapter = TMAPAdapter(transport, settings(), budget, clock=lambda: NOW)
    assert adapter.lookup(query()).failure == "quota"
    ticks[0] = 29.9
    assert adapter.lookup(query()).failure == "quota"
    assert len(transport.calls) == 1


def test_live_provider_falls_back_to_odsay_and_reports_all_provider_failures() -> None:
    primary_transport = MockTransport([TransportError("timeout"), TransportError("timeout")])
    fallback_transport = MockTransport(
        [HttpReply(200, {"result": {"paths": [{"pathType": 2, "totalTime": 22}]}}), TransportError("network")]
    )
    provider = LiveRouteProvider(tmap(primary_transport), odsay(fallback_transport), clock=lambda: NOW)
    success = provider.lookup(place("a"), place("b"), mode="TRANSIT")
    failed = provider.lookup(place("a"), place("b"), mode="TRANSIT")
    assert (success.provider, success.duration_min, success.failure) == ("ODSAY", 22, None)
    assert (failed.provider, failed.duration_min, failed.failure) == ("ODSAY", None, "network")


def test_live_provider_never_falls_back_car_and_rejects_bad_mode_coordinates_or_naive_departure() -> None:
    primary_transport = MockTransport([TransportError("timeout")])
    fallback_transport = MockTransport([])
    provider = LiveRouteProvider(tmap(primary_transport), odsay(fallback_transport), clock=lambda: NOW)
    car = provider.lookup(place("a"), place("b"), mode="CAR")
    mode = provider.lookup(place("a"), place("b"), mode=cast(Any, "BIKE"))
    bad = place("bad").model_construct(place_ref=PublicPlaceRef(place_id="bad"), lat=91.0, lng=129.0)
    coordinates = provider.lookup(bad, place("b"), mode="WALK")
    naive = provider.lookup(place("a"), place("b"), mode="TRANSIT", departure_at=datetime(2026, 11, 8, 12))
    assert [result.failure for result in (car, mode, coordinates, naive)] == [
        "timeout",
        "invalid_input",
        "invalid_input",
        "invalid_input",
    ]
    assert fallback_transport.calls == []


def test_live_estimate_is_deterministic_and_keeps_real_provider_source() -> None:
    payload = {"metaData": {"plan": {"itineraries": [{"totalTime": 1_200, "legs": [{"service": 1}]}]}}}
    transport = MockTransport([HttpReply(200, payload), HttpReply(200, payload)])
    provider = LiveRouteProvider(tmap(transport), clock=lambda: NOW)
    first = provider.estimate(place("a"), place("b"), mode="TRANSIT")
    second = provider.estimate(place("a"), place("b"), mode="TRANSIT")
    assert first == second
    assert (first.duration_min, first.source, first.computed_at) == (20, "TMAP", NOW)


def test_models_and_debug_logs_hide_key_names_and_coordinates(caplog: pytest.LogCaptureFixture) -> None:
    secret = "super-secret-route-key"
    secret_name = "synthetic-kakao-name"
    origin = place("a").model_copy(update={"name": secret_name, "lat": 35.1234567, "lng": 129.7654321})
    config = ProviderSettings(SecretStr(secret))
    route_query = RouteQuery(origin=origin, destination=place("b"), mode="TRANSIT")
    caplog.set_level("DEBUG")
    combined = repr(config) + repr(route_query) + route_query.model_dump_json() + caplog.text
    for hidden in (secret, secret_name, "35.1234567", "129.7654321"):
        assert hidden not in combined


@pytest.mark.parametrize(
    "mode,departure,path",
    [
        ("CAR", None, "/tmap/routes?version=1"),
        ("WALK", None, "/tmap/routes/pedestrian?version=1"),
        ("CAR", NOW, "/tmap/routes/prediction?version=1"),
    ],
)
def test_tmap_adapter_through_real_transport_preserves_required_version(monkeypatch, mode, departure, path):
    monkeypatch.setattr(FakeConnection, "instances", [])
    monkeypatch.setattr(FakeConnection, "error", None)
    monkeypatch.setattr(
        FakeConnection,
        "response",
        FakeResponse(
            body=json.dumps({"features": [{"properties": {"totalTime": 601}}]}).encode(),
        ),
    )
    monkeypatch.setattr("app.adapters.route.transport.http.client.HTTPSConnection", FakeConnection)
    adapter = TMAPAdapter(SafeHTTPTransport(), settings(), CallBudget(10), clock=lambda: NOW)
    result = adapter.lookup(query(mode, departure=departure))
    assert result.duration_min == 11
    assert FakeConnection.instances[0].request_args[1] == path
    assert FakeConnection.instances[0].closed


def test_odsay_adapter_through_real_transport_keeps_key_in_form_body(monkeypatch):
    from urllib.parse import parse_qs

    monkeypatch.setattr(FakeConnection, "instances", [])
    monkeypatch.setattr(FakeConnection, "error", None)
    monkeypatch.setattr(
        FakeConnection,
        "response",
        FakeResponse(
            body=b'{"result":{"paths":[{"pathType":2,"totalTime":17}]}}',
        ),
    )
    monkeypatch.setattr("app.adapters.route.transport.http.client.HTTPSConnection", FakeConnection)
    adapter = ODsayAdapter(SafeHTTPTransport(), settings(), CallBudget(10), search_timezone=KST, clock=lambda: NOW)
    result = adapter.lookup(query())
    assert result.duration_min == 17
    method, path, body, headers = FakeConnection.instances[0].request_args
    assert (method, path) == ("POST", "/v1/api/maasRP")
    assert parse_qs(body.decode())["apiKey"] == ["route-secret-key"]
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"


def test_departure_aware_transit_falls_back_without_ignoring_requested_time():
    primary_transport = MockTransport([])

    def check(url, headers, body, encoding, timeout):
        assert body["SearchTime"] == "202611081200"

    fallback_transport = MockTransport(
        [
            HttpReply(200, {"result": {"paths": [{"pathType": 2, "totalTime": 17}]}}),
        ],
        [check],
    )
    provider = LiveRouteProvider(tmap(primary_transport), odsay(fallback_transport))
    result = provider.lookup(place("a"), place("b"), mode="TRANSIT", departure_at=NOW)
    assert result.departure_applied and result.duration_min == 17
    assert result.provider == "ODSAY"
    assert not primary_transport.calls
