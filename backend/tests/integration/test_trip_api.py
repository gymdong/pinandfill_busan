import json
from datetime import date, time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.engine.schemas import KakaoPlaceRef, OpeningHours, ScheduleState
from app.modules.trips.repository import FakeTripRepository, TripRecord
from app.modules.trips.schemas import KakaoPlaceKey, PublicPlaceInput
from app.modules.trips.service import TripService
from tests.unit.engine.test_service import _block, _details, _engine, _trip


def setup_api(*, duration=15, fixed_at=time(11), hours=None):
    engine, places, routes = _engine(("a", "b", "new"), duration=duration)
    if hours is not None:
        places.details["new"] = _details("new", hours=hours)
    record = TripRecord(
        _trip(),
        ScheduleState(
            blocks=(
                _block("a", 1, arrive=time(9), depart=time(9, 30), fixed=True),
                _block("b", 2, arrive=fixed_at, depart=time(fixed_at.hour, 30), fixed=True),
            )
        ),
    )
    repository = FakeTripRepository({"trip": record})

    def stay(place: PublicPlaceInput | KakaoPlaceKey) -> int | None:
        key = place.place_id if isinstance(place, PublicPlaceInput) else place.kakao_place_id
        return 30 if key in {"new", "123"} else None

    application = create_app(trip_service=TripService(repository, engine, stay))
    return TestClient(application), repository, places, routes


def insertion(**overrides):
    return {
        "place": {"placeId": "new"},
        "isFixed": False,
        "origin": "USER",
        "fromBlockId": "a",
        "toBlockId": "b",
        **overrides,
    }


def test_insert_http_renumbers_and_preserves_fixed_then_generate():
    client, repository, _, _ = setup_api()
    before = repository.get("trip")
    response = client.post("/api/trips/trip/blocks", json=insertion())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert set(payload) == {"schedule", "violations"}
    blocks = payload["schedule"]["days"][0]["blocks"]
    assert [b["seq"] for b in blocks] == [10, 20, 30]
    assert [blocks[0]["id"], blocks[2]["id"]] == ["a", "b"]
    assert (blocks[0]["arriveAt"], blocks[2]["arriveAt"]) == ("09:00", "11:00")
    assert (blocks[1]["arriveAt"], blocks[1]["departAt"]) == ("09:45", "10:15")
    assert len(before.schedule.blocks) == 2
    assert len(repository.get("trip").schedule.blocks) == 3
    generated = client.post("/api/trips/trip/schedule", json={})
    assert generated.status_code == 200
    assert set(generated.json()) == {"days", "violations", "conflicts"}
    assert generated.json()["days"][0]["blocks"] == blocks


def test_fixed_insert_http_preserves_designated_window():
    client, repository, _, _ = setup_api()
    response = client.post(
        "/api/trips/trip/blocks",
        json=insertion(
            isFixed=True,
            fixedWindow={"dayNo": 1, "start": "10:00", "end": "10:30"},
        ),
    )
    assert response.status_code == 200
    block = repository.get("trip").schedule.blocks[1]
    assert (block.fixed_start, block.arrive_at, block.depart_at) == (time(10), time(10), time(10, 30))


@pytest.mark.parametrize("endpoint", ["blocks", "schedule"])
def test_fixed_time_conflict_returns_err009_without_saving(endpoint):
    client, repository, _, _ = setup_api(duration=45, fixed_at=time(10))
    original = repository.get("trip")
    response = client.post(f"/api/trips/trip/{endpoint}", json=insertion() if endpoint == "blocks" else {})
    assert response.status_code == 409
    assert response.json()["error"]["id"] == "ERR-009"
    assert "날짜 분리" in response.json()["error"]["message"]
    assert repository.get("trip") == original


def test_closed_day_is_warning_200_and_is_saved():
    client, repository, _, _ = setup_api(hours=OpeningHours(is_closed=True))
    response = client.post("/api/trips/trip/blocks", json=insertion())
    assert response.status_code == 200
    assert "CLOSED_DAY" in {v["type"] for v in response.json()["violations"]}
    assert len(repository.get("trip").schedule.blocks) == 3


@pytest.mark.parametrize("coords", [True, False])
def test_kakao_http_context_is_not_stored_logged_echoed_or_reused(coords, caplog):
    client, repository, places, routes = setup_api()
    body = insertion(place={"kakaoPlaceId": "123", "placeUrl": "https://place.map.kakao.com/123"})
    if coords:
        body["sessionCoords"] = {"123": {"lat": 35.1234567, "lng": 129.7654321}}
    response = client.post("/api/trips/trip/blocks", json=body)
    assert response.status_code == 200
    assert len(routes.calls) == (2 if coords else 0)
    place = response.json()["schedule"]["days"][0]["blocks"][1]["place"]
    assert place == {"source": "KAKAO", "kakaoPlaceId": "123", "placeUrl": "https://place.map.kakao.com/123"}
    saved = repository.get("trip").schedule
    assert isinstance(saved.blocks[1].place_ref, KakaoPlaceRef)
    assert "123" not in places.calls
    for secret in ("35.1234567", "129.7654321", "sessionCoords"):
        assert secret not in response.text + saved.model_dump_json() + caplog.text + repr(repository.get("trip"))
    assert saved.legs[0].duration_min == (15 if coords else None)
    calls = len(routes.calls)
    again = client.post("/api/trips/trip/schedule", json={})
    assert again.status_code == 200
    assert len(routes.calls) == calls
    assert all(leg["durationMin"] is None for leg in again.json()["days"][0]["legs"])
    assert "COORDS_NEEDS_CHECK" in {v["type"] for v in again.json()["violations"]}


@pytest.mark.parametrize(
    "patch",
    [
        {"fromBlockId": "b", "toBlockId": "a"},
        {"fromBlockId": "absent"},
        {"toBlockId": None},
        {"fromBlockId": None, "toBlockId": None},
        {"place": {"placeId": "no-duration"}},
    ],
)
def test_bad_insertion_returns_err001_and_keeps_state(patch):
    client, repository, _, _ = setup_api()
    before = repository.get("trip")
    response = client.post("/api/trips/trip/blocks", json=insertion(**patch))
    assert response.status_code == 400
    assert response.json()["error"]["id"] == "ERR-001"
    assert repository.get("trip") == before


@pytest.mark.parametrize("endpoint", ["blocks", "schedule"])
def test_invalid_request_hides_kakao_input(endpoint, caplog):
    client, repository, _, _ = setup_api()
    before = repository.get("trip")
    secret = "synthetic-kakao-name-35.1234567"
    body = insertion() if endpoint == "blocks" else {}
    body["sessionCoords"] = {"123": {"lat": secret, "lng": 129.7654321, "name": secret}}
    response = client.post(f"/api/trips/trip/{endpoint}", json=body)
    assert response.status_code == 400
    assert response.json()["error"]["id"] == "ERR-001"
    assert secret not in response.text + caplog.text
    assert "129.7654321" not in response.text + caplog.text
    assert repository.get("trip") == before


def test_provider_exception_is_sanitized_and_does_not_save(caplog):
    client, repository, _, routes = setup_api()
    before = repository.get("trip")
    secret = "synthetic-kakao-name-35.1234567"

    def fail(*args, **kwargs):
        raise RuntimeError(secret)

    routes.estimate = fail
    response = client.post("/api/trips/trip/schedule", json={})
    assert response.status_code == 503
    assert response.json()["error"]["id"] == "ERR-017"
    assert secret not in response.text + caplog.text
    assert repository.get("trip") == before


def test_missing_trip_and_unagreed_options():
    client, repository, _, _ = setup_api()
    before = repository.get("trip")
    response = client.post("/api/trips/missing/schedule", json={})
    assert response.status_code == 404
    assert response.json()["error"]["id"] == "ERR-016"
    response = client.post("/api/trips/trip/schedule", json={"options": {"auto": True}})
    assert response.status_code == 400
    assert repository.get("trip") == before


def test_schedule_recomputes_each_day_without_cross_day_routes():
    client, repository, _, routes = setup_api()
    record = repository.get("trip")
    day_two = tuple(block.model_copy(update={"id": block.id + "2", "day_no": 2}) for block in record.schedule.blocks)
    repository.save(
        "trip", TripRecord(_trip(end_date=date(2026, 11, 3)), ScheduleState(blocks=(*record.schedule.blocks, *day_two)))
    )
    response = client.post("/api/trips/trip/schedule", json={})
    assert response.status_code == 200
    assert len(response.json()["days"]) == 2
    assert routes.calls == [("a", "b"), ("a", "b")]
    assert len(repository.get("trip").schedule.legs) == 2


@pytest.mark.parametrize("empty", [True, False])
def test_initial_schedule_without_explicit_anchor_is_not_invented(empty):
    client, repository, _, _ = setup_api()
    record = repository.get("trip")
    blocks = () if empty else (_block("a", 1, arrive=None, depart=None),)
    record = TripRecord(record.trip, ScheduleState(blocks=blocks))
    repository.save("trip", record)
    response = client.post("/api/trips/trip/schedule", json={})
    assert response.status_code == 400
    assert repository.get("trip") == record
    assert "sessionCoords" not in json.dumps(response.json())


def test_multiday_generation_preserves_earlier_day_overflow():
    client, repository, _, _ = setup_api(duration=20)
    state = ScheduleState(
        blocks=(
            _block("a", 1, arrive=time(23), depart=time(23, 30), fixed=True),
            _block("new", 2, arrive=None, depart=None),
            _block("b", 1, arrive=time(9), depart=time(9, 30), fixed=True, day_no=2),
        )
    )
    repository.save("trip", TripRecord(_trip(end_date=date(2026, 11, 3)), state))
    for _ in range(2):
        response = client.post("/api/trips/trip/schedule", json={})
        assert response.status_code == 200
        assert "DAY_OVERFLOW" in {v["type"] for v in response.json()["violations"]}
        assert any(c["blockIds"] == ["new"] for c in response.json()["conflicts"])


def test_generation_uses_explicit_fixed_window_for_first_block():
    client, repository, _, _ = setup_api()
    record = repository.get("trip")
    first = record.schedule.blocks[0].model_copy(update={"arrive_at": None, "depart_at": None})
    repository.save("trip", TripRecord(record.trip, ScheduleState(blocks=(first, *record.schedule.blocks[1:]))))
    response = client.post("/api/trips/trip/schedule", json={})
    assert response.status_code == 200
    assert response.json()["days"][0]["blocks"][0]["arriveAt"] == "09:00"


def test_later_day_failure_does_not_save_earlier_day_calculations():
    client, repository, _, _ = setup_api(duration=45)
    state = ScheduleState(
        blocks=(
            _block("a", 1, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("new", 2, arrive=None, depart=None),
            _block("a2", 1, place_id="a", arrive=time(9), depart=time(9, 30), fixed=True, day_no=2),
            _block("b", 2, arrive=time(10), depart=time(10, 30), fixed=True, day_no=2),
        )
    )
    record = TripRecord(_trip(end_date=date(2026, 11, 3)), state)
    repository.save("trip", record)
    response = client.post("/api/trips/trip/schedule", json={})
    assert response.status_code == 409
    assert repository.get("trip") == record
