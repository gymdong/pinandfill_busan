from datetime import UTC, date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient

from app.adapters.route.service import LiveRouteProvider
from app.adapters.route.transport import HttpReply
from app.main import create_app
from app.modules.engine import routing
from app.modules.engine.interfaces import RouteEstimate
from app.modules.engine.schemas import (
    KakaoPlaceRef,
    OpeningHours,
    RecomputeInput,
    ScheduleState,
    ValidateInput,
)
from app.modules.engine.service import BasicItineraryEngine
from app.modules.recommend.waypoints import ScoreWeights, WaypointRecommender
from app.modules.trips.repository import FakeTripRepository, TripRecord
from app.modules.trips.service import TripService
from tests.integration.test_route_http_api import client_with_routes, transit_payload
from tests.integration.test_waypoint_api import FakeCandidates, _candidate
from tests.unit.engine.test_route_providers import KST, NOW, MockTransport, odsay, place, tmap
from tests.unit.engine.test_service import FakePlaces, _block, _details, _trip


class TimedRoutes:
    def __init__(self, durations=None):
        self.calls = []
        self.durations = durations or {}

    def estimate(self, *args, **kwargs):
        raise AssertionError("Departure-aware providers must receive estimate_at")

    def estimate_at(self, origin, destination, *, mode, departure_at):
        pair = (origin.place_ref.place_id, destination.place_ref.place_id)
        self.calls.append((*pair, departure_at))
        duration = self.durations.get((*pair, departure_at.time()), self.durations.get(pair, 15))
        return RouteEstimate(duration, "TMAP", NOW, time_semantics="prediction", lookup_failed=duration is None)


def engine_for(ids, routes):
    places = FakePlaces(
        {pid: _details(pid, hours=OpeningHours(open_time=time(0), close_time=time(23, 59))) for pid in ids}
    )
    return BasicItineraryEngine(places, routes, clock=lambda: NOW), places


def test_engine_passes_second_day_date_and_calculated_departures():
    routes = TimedRoutes({("a", "b"): 20, ("b", "c"): 10})
    engine, _ = engine_for(("a", "b", "c"), routes)
    state = ScheduleState(
        blocks=(
            _block("a", 1, arrive=time(9), depart=time(9, 30), fixed=True, day_no=2),
            _block("b", 2, arrive=None, depart=None, stay=40, day_no=2),
            _block("c", 3, arrive=time(11), depart=time(11, 30), fixed=True, day_no=2),
        )
    )
    result = engine.recompute(RecomputeInput(trip=_trip(end_date=date(2026, 11, 3)), schedule=state, from_block_id="a"))
    assert routes.calls == [
        ("a", "b", datetime(2026, 11, 3, 9, 30, tzinfo=KST)),
        ("b", "c", datetime(2026, 11, 3, 10, 30, tzinfo=KST)),
    ]
    assert str(routes.calls[0][2].tzinfo) == "Asia/Seoul"
    assert result.state.blocks[1].arrive_at == time(9, 50)
    assert result.state.blocks[1].depart_at == time(10, 30)
    assert result.state.blocks[2] == state.blocks[2]


def test_unknown_departure_skips_routes_and_can_resume_after_fixed_block():
    routes = TimedRoutes()
    engine, _ = engine_for(("a", "b", "c", "d"), routes)
    state = ScheduleState(
        blocks=(
            _block("a", 1, arrive=None, depart=None),
            _block("b", 2, arrive=None, depart=None),
            _block("c", 3, arrive=time(11), depart=time(11, 30), fixed=True),
            _block("d", 4, arrive=None, depart=None),
        )
    )
    result = engine.recompute(RecomputeInput(trip=_trip(), schedule=state, from_block_id="a"))
    assert routes.calls == [("c", "d", datetime(2026, 11, 2, 11, 30, tzinfo=KST))]
    assert [leg.duration_min for leg in result.state.legs] == [None, None, 15]
    assert "DEPARTURE_TIME_NEEDS_CHECK" in {v.type for v in result.schedule.violations}


@pytest.mark.parametrize("duration", [9, 10, 20])
def test_midnight_boundary_is_not_rolled_into_wrong_day(duration):
    routes = TimedRoutes({("a", "b"): duration})
    engine, _ = engine_for(("a", "b", "c"), routes)
    state = ScheduleState(
        blocks=(
            _block("a", 1, arrive=time(23), depart=time(23, 30), fixed=True),
            _block("b", 2, arrive=None, depart=None, stay=20),
            _block("c", 3, arrive=None, depart=None),
        )
    )
    result = engine.recompute(RecomputeInput(trip=_trip(), schedule=state, from_block_id="a"))
    assert routes.calls[0][2] == datetime(2026, 11, 2, 23, 30, tzinfo=KST)
    if duration == 9:
        assert routes.calls[1][2] == datetime(2026, 11, 2, 23, 59, tzinfo=KST)
        assert result.state.blocks[1].depart_at == time(23, 59)
    else:
        assert len(routes.calls) == 1
        assert result.state.blocks[1].depart_at is None
        assert "DAY_OVERFLOW" in {v.type for v in result.schedule.violations}


def test_api009_day_change_uses_local_midnight_without_cross_day_route():
    routes = TimedRoutes()
    engine, _ = engine_for(("a", "b", "c", "d"), routes)
    trip = _trip(end_date=date(2026, 11, 3)).model_copy(update={"day_start": time(0)})
    state = ScheduleState(
        blocks=(
            _block("a", 1, arrive=time(22), depart=time(22, 30), fixed=True),
            _block("b", 2, arrive=None, depart=None),
            _block("c", 1, arrive=time(0), depart=time(0, 30), fixed=True, day_no=2),
            _block("d", 2, arrive=None, depart=None, day_no=2),
        )
    )
    repository = FakeTripRepository({"trip": TripRecord(trip, state)})
    client = TestClient(create_app(trip_service=TripService(repository, engine, lambda _: 30)))
    response = client.post("/api/trips/trip/schedule", json={})
    assert response.status_code == 200
    assert routes.calls == [
        ("a", "b", datetime(2026, 11, 2, 22, 30, tzinfo=KST)),
        ("c", "d", datetime(2026, 11, 3, 0, 30, tzinfo=KST)),
    ]


@pytest.mark.parametrize("fixed_start,expected", [(time(10, 15), True), (time(9, 59), False)])
def test_waypoint_departure_after_stay_changes_travel_and_preserves_fixed(fixed_start, expected):
    routes = TimedRoutes({("a", "b"): 10, ("a", "x"): 5, ("x", "b"): 100, ("x", "b", time(9, 55)): 7})
    engine, places = engine_for(("a", "b", "x"), routes)
    fixed_end = (datetime.combine(date(2026, 11, 2), fixed_start) + timedelta(minutes=30)).time()
    state = ScheduleState(
        blocks=(
            _block("a", 1, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 2, arrive=fixed_start, depart=fixed_end, fixed=True),
        )
    )
    record = TripRecord(_trip(), state)
    repository = FakeTripRepository({"trip": record})
    recommender = WaypointRecommender(
        FakeCandidates((_candidate("x", stay=20),)),
        places,
        routes,
        ScoreWeights(preference=1, representativeness=1, detour=1, crowd=1, missing_crowd_penalty=0),
    )
    client = TestClient(create_app(trip_service=TripService(repository, engine, lambda _: 20, recommender=recommender)))
    response = client.post(
        "/api/trips/trip/waypoints/suggest",
        json={
            "fromBlockId": "a",
            "toBlockId": "b",
            "thresholdMin": 10,
        },
    )
    assert response.status_code == 200
    assert routes.calls == [
        ("a", "b", datetime(2026, 11, 2, 9, 30, tzinfo=KST)),
        ("a", "x", datetime(2026, 11, 2, 9, 30, tzinfo=KST)),
        ("x", "b", datetime(2026, 11, 2, 9, 55, tzinfo=KST)),
    ]
    assert [c["detourMin"] for c in response.json()["candidates"]] == ([2] if expected else [])
    assert repository.get("trip") == record


def test_tmap_transit_receives_seoul_schedule_context_not_current_time():
    client, repository, primary, _ = client_with_routes([HttpReply(200, transit_payload(600))])
    times = []

    def check(url, headers, body, encoding, timeout):
        times.append(body["searchDttm"])
        assert "predictionTime" not in body

    primary.validators.append(check)
    response = client.post("/api/trips/trip/schedule", json={})
    assert response.status_code == 200
    assert times == ["202611020930"]
    leg = repository.get("trip").schedule.legs[0]
    assert leg.time_semantics == "service_availability"
    assert "ROUTE_TIME_CONTEXT_ONLY" in {v["type"] for v in response.json()["violations"]}
    assert "timeSemantics" not in response.json()["days"][0]["legs"][0]


def test_tmap_car_engine_uses_prediction_and_keeps_fixed_conflict():
    client, repository, primary, _ = client_with_routes(
        [HttpReply(200, {"features": [{"properties": {"totalTime": 3600}}]})]
    )
    record = repository.get("trip")
    fixed = _block("b", 20, arrive=time(10), depart=time(10, 30), fixed=True)
    record = TripRecord(
        record.trip.model_copy(update={"transport_mode": "CAR"}),
        ScheduleState(blocks=(record.schedule.blocks[0], fixed)),
    )
    repository.save("trip", record)

    def check(url, headers, body, encoding, timeout):
        assert url.endswith("prediction?version=1")
        assert body["routesInfo"]["predictionTime"] == "2026-11-02T09:30:00+0900"

    primary.validators.append(check)
    response = client.post("/api/trips/trip/schedule", json={})
    assert response.status_code == 409
    assert response.json()["error"]["id"] == "ERR-009"
    assert repository.get("trip") == record


def test_odsay_searchtime_is_context_not_prediction_and_fallback_keeps_departure():
    client, repository, primary, fallback = client_with_routes(
        [HttpReply(500, {})],
        fallback_replies=[HttpReply(200, {"result": {"paths": [{"pathType": 2, "totalTime": 12}]}})],
    )

    def check(url, headers, body, encoding, timeout):
        assert body["SearchTime"] == "202611020930"

    fallback.validators.append(check)
    response = client.post("/api/trips/trip/schedule", json={})
    assert response.status_code == 200
    assert primary.calls == ["transit"] and fallback.calls == ["v1"]
    assert repository.get("trip").schedule.legs[0].time_semantics == "search_context"
    assert "ROUTE_TIME_CONTEXT_ONLY" in {v["type"] for v in response.json()["violations"]}


def test_all_failed_routes_are_explicitly_unconfirmed_after_revalidation():
    client, repository, _, _ = client_with_routes([HttpReply(500, {})], fallback_replies=[HttpReply(500, {})])
    response = client.post("/api/trips/trip/schedule", json={})
    assert response.status_code == 200
    assert response.json()["days"][0]["legs"] == []
    assert repository.get("trip").schedule.legs[0].source == "UNKNOWN"
    record = repository.get("trip")
    assert record.schedule.legs[0].lookup_failed
    assert "ROUTE_LOOKUP_FAILED" in {v["type"] for v in response.json()["violations"]}
    report = client.app.state.trip_service.engine.validate(ValidateInput(trip=record.trip, schedule=record.schedule))
    assert "ROUTE_LOOKUP_FAILED" in {v.type for v in report.violations}


def test_missing_departure_never_reaches_live_adapter_clock_fallback():
    client, repository, primary, fallback = client_with_routes([])
    record = repository.get("trip")
    state = ScheduleState(
        blocks=(
            record.schedule.blocks[0].model_copy(update={"depart_at": None}),
            record.schedule.blocks[1],
        )
    )
    result = client.app.state.trip_service.engine.recompute(
        RecomputeInput(trip=record.trip, schedule=state, from_block_id="a")
    )
    assert result.state.legs[0].duration_min is None
    assert not primary.calls and not fallback.calls


def test_missing_departure_estimate_at_is_rejected_before_network():
    primary, fallback = MockTransport([]), MockTransport([])
    provider = LiveRouteProvider(tmap(primary), odsay(fallback))
    result = provider.estimate_at(place("a"), place("b"), mode="TRANSIT", departure_at=None)
    assert result.duration_min is None and result.lookup_failed
    assert not primary.calls and not fallback.calls


def test_timezone_fallback_is_bounded_and_does_not_use_machine_timezone(monkeypatch):
    monkeypatch.setattr(routing, "_SEOUL", None)
    value = routing.seoul_datetime(date(2026, 11, 2), time(0, 15))
    assert value.isoformat() == "2026-11-02T00:15:00+09:00"
    assert value.astimezone(UTC).date() == date(2026, 11, 1)
    assert routing.seoul_datetime(date(1988, 5, 1), time(12)) is None


def test_timed_provider_exception_does_not_expose_request_secrets(caplog):
    secret = "synthetic-kakao-secret-35.1234567-key"
    client, repository, primary, fallback = client_with_routes(
        [RuntimeError(secret)], fallback_replies=[RuntimeError(secret)]
    )
    record = repository.get("trip")
    first = record.schedule.blocks[0].model_copy(
        update={
            "place_ref": KakaoPlaceRef(
                kakao_place_id="123",
                kakao_place_url="https://place.map.kakao.com/123",
            )
        }
    )
    repository.save("trip", TripRecord(record.trip, ScheduleState(blocks=(first, record.schedule.blocks[1]))))

    def check(url, headers, body, encoding, timeout):
        assert float(body.get("startY", body.get("SY"))) == 35.1234567

    primary.validators.append(check)
    fallback.validators.append(check)
    with caplog.at_level("DEBUG"):
        response = client.post(
            "/api/trips/trip/schedule",
            json={"sessionCoords": {"123": {"lat": 35.1234567, "lng": 129.7654321}}},
        )
    assert response.status_code == 200
    combined = response.text + caplog.text + repository.get("trip").schedule.model_dump_json()
    assert secret not in combined and "35.1234567" not in combined and "129.7654321" not in combined


@pytest.mark.parametrize(
    "mode,expected,applied",
    [
        ("CAR", "prediction", True),
        ("TRANSIT", "service_availability", True),
        ("WALK", "static", False),
    ],
)
def test_provider_time_semantics_distinguish_prediction_from_parameter_application(mode, expected, applied):
    payload = transit_payload(600) if mode == "TRANSIT" else {"features": [{"properties": {"totalTime": 600}}]}
    transport = MockTransport([HttpReply(200, payload)])
    provider = LiveRouteProvider(tmap(transport))
    result = provider.lookup(place("a"), place("b"), mode=mode, departure_at=NOW, allow_time_context=True)
    assert result.duration_min == 10
    assert result.time_semantics == expected
    assert result.departure_applied == applied
    assert result.failure is None


def test_recommendation_without_departure_does_not_query_baseline_or_candidates():
    routes = TimedRoutes()
    engine, places = engine_for(("a", "b", "x"), routes)
    provider = FakeCandidates((_candidate("x"),))
    recommender = WaypointRecommender(
        provider,
        places,
        routes,
        ScoreWeights(preference=1, representativeness=1, detour=1, crowd=1, missing_crowd_penalty=0),
    )
    state = ScheduleState(
        blocks=(
            _block("a", 1, arrive=time(9), depart=None),
            _block("b", 2, arrive=time(11), depart=time(11, 30), fixed=True),
        )
    )
    repository = FakeTripRepository({"trip": TripRecord(_trip(), state)})
    client = TestClient(create_app(trip_service=TripService(repository, engine, lambda _: 30, recommender=recommender)))
    response = client.post(
        "/api/trips/trip/waypoints/suggest",
        json={
            "fromBlockId": "a",
            "toBlockId": "b",
            "thresholdMin": 15,
        },
    )
    assert response.status_code == 200 and response.json() == {"candidates": []}
    assert not routes.calls and not provider.calls
