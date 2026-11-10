from datetime import UTC, datetime, time
from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.adapters.route.providers import ODsayAdapter, ProviderSettings, TMAPAdapter
from app.adapters.route.quota import CallBudget
from app.adapters.route.service import LiveRouteProvider
from app.adapters.route.transport import HttpReply
from app.main import create_app
from app.modules.engine.schemas import KakaoPlaceRef, OpeningHours, ScheduleState
from app.modules.engine.service import BasicItineraryEngine
from app.modules.recommend.waypoints import ScoreWeights, WaypointRecommender
from app.modules.trips.repository import FakeTripRepository, TripRecord
from app.modules.trips.service import TripService
from tests.integration.test_waypoint_api import FakeCandidates, _candidate
from tests.unit.engine.test_route_providers import KST, MockTransport
from tests.unit.engine.test_service import FakePlaces, _block, _details, _trip

NOW = datetime(2026, 11, 8, 3, tzinfo=UTC)


def client_with_routes(
    replies: list[HttpReply | Exception], *, fallback_replies: list[HttpReply | Exception] | None = None
) -> tuple[TestClient, FakeTripRepository, MockTransport, MockTransport]:
    places = FakePlaces(
        {
            place_id: _details(place_id, hours=OpeningHours(open_time=time(8), close_time=time(20)))
            for place_id in ("a", "b", "new")
        }
    )
    primary_transport = MockTransport(replies)
    fallback_transport = MockTransport(fallback_replies or [])
    settings = ProviderSettings(SecretStr("mock-route-key"), timeout_seconds=2)
    primary = TMAPAdapter(primary_transport, settings, CallBudget(100), clock=lambda: NOW)
    fallback = ODsayAdapter(fallback_transport, settings, CallBudget(100), search_timezone=KST, clock=lambda: NOW)
    routes = LiveRouteProvider(primary, fallback, clock=lambda: NOW)
    engine = BasicItineraryEngine(places, routes, clock=lambda: NOW)
    state = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 20, arrive=time(10), depart=time(10, 30)),
        )
    )
    repository = FakeTripRepository({"trip": TripRecord(_trip(), state)})
    service = TripService(repository, engine, lambda place: 30)
    return TestClient(create_app(trip_service=service)), repository, primary_transport, fallback_transport


def transit_payload(seconds: int) -> dict[str, Any]:
    return {"metaData": {"plan": {"itineraries": [{"totalTime": seconds, "legs": [{"mode": "BUS", "service": 1}]}]}}}


def test_api009_serializes_tmap_duration_source_and_timestamp() -> None:
    client, repository, primary, fallback = client_with_routes([HttpReply(200, transit_payload(1_800))])
    before = repository.get("trip")
    response = client.post("/api/trips/trip/schedule", json={})
    assert response.status_code == 200
    leg = response.json()["days"][0]["legs"][0]
    assert {key: value for key, value in leg.items() if key != "id"} == {
        "fromBlockId": "a",
        "toBlockId": "b",
        "mode": "TRANSIT",
        "durationMin": 30,
        "computedAt": "2026-11-08T03:00:00Z",
        "source": "TMAP",
    }
    assert response.json()["days"][0]["blocks"][1]["arriveAt"] == "10:00"
    assert primary.calls == ["transit"]
    assert fallback.calls == []
    assert before.schedule.legs == ()
    assert repository.get("trip").schedule.legs[0].source == "TMAP"


def test_api009_uses_odsay_fallback_and_serializes_real_source() -> None:
    fallback_payload = {"result": {"paths": [{"pathType": 2, "totalTime": 30}]}}
    client, repository, primary, fallback = client_with_routes(
        [HttpReply(500, {})], fallback_replies=[HttpReply(200, fallback_payload)]
    )
    response = client.post("/api/trips/trip/schedule", json={})
    assert response.status_code == 200
    leg = response.json()["days"][0]["legs"][0]
    assert (leg["durationMin"], leg["source"]) == (30, "ODSAY")
    assert (primary.calls, fallback.calls) == (["transit"], ["v1"])
    assert repository.get("trip").schedule.legs[0].source == "ODSAY"


def test_api009_all_providers_fail_without_inventing_duration() -> None:
    client, repository, _, _ = client_with_routes([HttpReply(500, {})], fallback_replies=[HttpReply(500, {})])
    response = client.post("/api/trips/trip/schedule", json={})
    assert response.status_code == 200
    leg = response.json()["days"][0]["legs"][0]
    assert leg["durationMin"] is None
    assert leg["source"] == "ODSAY"
    assert response.json()["days"][0]["blocks"][1]["arriveAt"] is None
    assert "TRAVEL_TIME_NEEDS_CHECK" in {item["type"] for item in response.json()["violations"]}
    assert repository.get("trip").schedule.legs[0].duration_min is None


def test_api006_uses_live_route_provider_without_changing_contract() -> None:
    # Insert computes a->new and new->b, both from mocked TMAP responses.
    client, repository, _, _ = client_with_routes(
        [HttpReply(200, transit_payload(600)), HttpReply(200, transit_payload(600))]
    )
    response = client.post(
        "/api/trips/trip/blocks",
        json={
            "place": {"placeId": "new"},
            "isFixed": False,
            "origin": "USER",
            "fromBlockId": "a",
            "toBlockId": "b",
        },
    )
    assert response.status_code == 200
    assert set(response.json()) == {"schedule", "violations"}
    legs = response.json()["schedule"]["days"][0]["legs"]
    assert [(leg["durationMin"], leg["source"]) for leg in legs] == [(10, "TMAP"), (10, "TMAP")]
    assert all(leg.source == "TMAP" for leg in repository.get("trip").schedule.legs)


def test_kakao_http_route_data_is_never_persisted_logged_or_reused(caplog, capsys):
    secret_name = "synthetic-kakao-route-name"
    lat, lng = 35.1234567, 129.7654321
    payload = transit_payload(600)
    payload["metaData"]["requestParameters"] = {"startY": lat, "startX": lng, "name": secret_name}
    client, repository, primary, fallback = client_with_routes([HttpReply(200, payload)])
    original = repository.get("trip")
    kakao = KakaoPlaceRef(kakao_place_id="123", kakao_place_url="https://place.map.kakao.com/123")
    first = original.schedule.blocks[0].model_copy(update={"place_ref": kakao})
    repository.save("trip", TripRecord(original.trip, ScheduleState(blocks=(first, original.schedule.blocks[1]))))

    def check(url, headers, body, encoding, timeout):
        assert body["startY"] == str(lat) and body["startX"] == str(lng)
        assert secret_name not in repr(body)

    primary.validators.append(check)
    with caplog.at_level("DEBUG"):
        response = client.post("/api/trips/trip/schedule", json={"sessionCoords": {"123": {"lat": lat, "lng": lng}}})
        again = client.post("/api/trips/trip/schedule", json={})
    assert response.status_code == again.status_code == 200
    assert response.json()["days"][0]["legs"][0]["durationMin"] == 10
    assert again.json()["days"][0]["legs"][0]["durationMin"] is None
    assert primary.calls == ["transit"] and fallback.calls == []
    captured = capsys.readouterr()
    text = response.text + again.text + repository.get("trip").schedule.model_dump_json()
    text += repr(primary) + repr(fallback) + caplog.text + captured.out + captured.err
    for secret in (secret_name, str(lat), str(lng), "mock-route-key"):
        assert secret not in text


def test_api011_uses_route_adapters_for_detour_without_saving():
    client, repository, primary, _ = client_with_routes([HttpReply(200, transit_payload(600)) for _ in range(3)])
    service = client.app.state.trip_service
    service.recommender = WaypointRecommender(
        FakeCandidates((_candidate("new"),)),
        service.engine.places,
        service.engine.routes,
        ScoreWeights(preference=1, representativeness=1, detour=1, crowd=1, missing_crowd_penalty=0),
    )
    before = repository.get("trip")
    response = client.post(
        "/api/trips/trip/waypoints/suggest",
        json={
            "fromBlockId": "a",
            "toBlockId": "b",
            "thresholdMin": 15,
        },
    )
    assert response.status_code == 200
    assert response.json()["candidates"][0]["detourMin"] == 10
    assert primary.calls == ["transit"] * 3
    assert repository.get("trip") == before
