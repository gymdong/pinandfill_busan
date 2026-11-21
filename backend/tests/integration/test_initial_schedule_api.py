"""API-009 initial generation: HTTP contracts, persistence and edit interoperability."""

from datetime import date
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.engine.initial import InitialSchedulePlanner
from app.modules.engine.schemas import OpeningHours, ScheduleState
from app.modules.engine.service import BasicItineraryEngine
from app.modules.trips.repository import FakeTripRepository, TripRecord
from app.modules.trips.service import TripService
from tests.unit.engine.test_initial import Places, Routes, Stays, command

TRIP = "initial-trip"
URL = f"/api/trips/{TRIP}/schedule"
KAKAO = {"kakaoPlaceId": "900000009", "placeUrl": "https://place.map.kakao.com/900000009"}
COORDS = {"900000009": {"lat": 35.9876543, "lng": 129.9876543}}


def item(key="a", **kwargs):
    return {"clientId": f"selection-{key}", "place": {"placeId": key}, **kwargs}


def body(*selections, **kwargs):
    return {"initial": {"policy": "FIRST_FEASIBLE", "selections": list(selections)}, **kwargs}


def pinned(key, start="10:00", end="10:30", **kwargs):
    return item(key, fixedWindow={"dayNo": 1, "start": start, "end": end}, **kwargs)


def setup_api(stay=30, days=1):
    places, routes, stays = Places(), Routes(), Stays(stay)
    engine = BasicItineraryEngine(places, routes)
    record = TripRecord(command(days=days).trip, ScheduleState())
    repository = FakeTripRepository({TRIP: record})
    service = TripService(
        repository,
        engine,
        lambda place: stay,
        initial_planner=InitialSchedulePlanner(engine, stays),
    )
    return TestClient(create_app(trip_service=service)), service, repository, places, routes


def blocks(payload):
    return [block for day in payload["days"] for block in day["blocks"]]


def assert_error(response, status=400, error_id="ERR-001"):
    assert response.status_code == status, response.text
    assert response.json()["error"]["id"] == error_id
    assert response.headers["cache-control"] == "no-store"


def test_initial_generation_saves_server_uuids_and_preserves_trip():
    client, service, repository, _, routes = setup_api()
    before = repository.get(TRIP)
    response = client.post(URL, json=body(pinned("a"), item("b", stayMin=45)))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert set(result) == {"days", "violations", "conflicts", "generation"}
    assert result["generation"] == {"saved": True, "confirmed": True, "unplaced": []}
    values = blocks(result)
    assert len(values) == 2 and {UUID(value["id"]).version for value in values} == {4}
    assert not {value["id"] for value in values} & {"selection-a", "selection-b"}
    fixed = next(value for value in values if value["place"]["id"] == "a")
    flexible = next(value for value in values if value["place"]["id"] == "b")
    assert fixed["isFixed"] and (fixed["arriveAt"], fixed["departAt"]) == ("10:00", "10:30")
    assert not flexible["isFixed"] and flexible["stayMin"] == 45
    assert repository.get(TRIP).trip == before.trip
    assert len(repository.get(TRIP).schedule.blocks) == 2
    assert service.history.latest_edit(TRIP) is None
    assert routes.departures


def test_multiple_dates_and_client_order_do_not_become_block_identifiers():
    client, _, repository, _, _ = setup_api(days=2)
    response = client.post(URL, json=body(item("a", dayNo=2), item("b", dayNo=1)))
    assert response.status_code == 200, response.text
    assert [(b["place"]["id"], b["dayNo"], b["seq"]) for b in blocks(response.json())] == [("b", 1, 1), ("a", 2, 1)]
    assert "selection-" not in repository.get(TRIP).schedule.model_dump_json()


def test_partial_result_returns_client_id_without_saving_or_discarding_history():
    client, service, repository, _, _ = setup_api(stay=None)
    before = repository.get(TRIP)
    old_edit = service.history.record_before_edit(TRIP, ScheduleState())
    response = client.post(URL, json=body(item("a", stayMin=30), item("missing-stay")))
    assert response.status_code == 200, response.text
    result = response.json()
    assert not result["generation"]["saved"]
    assert result["generation"]["unplaced"][0]["clientId"] == "selection-missing-stay"
    assert result["generation"]["unplaced"][0]["reason"]["type"] == "STAY_NEEDS_CHECK"
    assert len(blocks(result)) == 1
    assert repository.get(TRIP) == before
    assert service.history.latest_edit(TRIP) == old_edit


def test_all_unplaced_still_returns_preview_and_never_saves():
    client, _, repository, _, _ = setup_api(stay=None)
    before = repository.get(TRIP)
    response = client.post(URL, json=body(item()))
    assert response.status_code == 200, response.text
    assert not response.json()["generation"]["saved"]
    assert blocks(response.json()) == []
    assert repository.get(TRIP) == before


def test_success_discards_previous_edit_snapshot():
    client, service, _, _, _ = setup_api()
    service.history.record_before_edit(TRIP, ScheduleState())
    assert client.post(URL, json=body(item())).status_code == 200
    assert service.history.latest_edit(TRIP) is None


def test_nonempty_schedule_cannot_be_overwritten():
    client, service, repository, _, _ = setup_api()
    assert client.post(URL, json=body(item())).status_code == 200
    before = repository.get(TRIP)
    old_edit = service.history.record_before_edit(TRIP, before.schedule)
    assert_error(client.post(URL, json=body(item("different"))))
    assert repository.get(TRIP) == before
    assert service.history.latest_edit(TRIP) == old_edit


@pytest.mark.parametrize("options", [None, {}, {"anything": True}])
def test_initial_and_explicit_options_are_mutually_exclusive(options):
    client, _, repository, _, _ = setup_api()
    assert_error(client.post(URL, json=body(item(), options=options)))
    assert repository.get(TRIP).schedule == ScheduleState()


@pytest.mark.parametrize(
    "selection",
    [
        item(dayNo=0),
        item(dayNo=2),
        item(stayMin=0),
        item(stayMin=True),
        item(stayMin="30"),
        item(stayMin=1441),
        item(clientId=""),
        item(isFixed=True),
        pinned("a", dayNo=2),
        pinned("a", start="11:00", end="10:00"),
        pinned("a", stayMin=60),
    ],
)
def test_invalid_initial_selection_has_sanitized_input_error(selection):
    client, _, repository, _, _ = setup_api()
    assert_error(client.post(URL, json=body(selection)))
    assert repository.get(TRIP).schedule == ScheduleState()


@pytest.mark.parametrize(
    "initial",
    [
        {"policy": "FIRST_FEASIBLE", "selections": []},
        {"policy": "OPTIMAL", "selections": [item()]},
        {"policy": "FIRST_FEASIBLE", "selections": [item(), item()]},
    ],
)
def test_invalid_initial_policy_or_selection_identity(initial):
    client, _, _, _, _ = setup_api()
    assert_error(client.post(URL, json={"initial": initial}))


def test_fixed_time_conflict_is_rejected_and_old_history_survives():
    client, service, repository, _, _ = setup_api()
    before = repository.get(TRIP)
    previous = service.history.record_before_edit(TRIP, before.schedule)
    response = client.post(URL, json=body(pinned("a"), pinned("b", "10:35", "11:05")))
    assert_error(response, 409, "ERR-009")
    assert repository.get(TRIP) == before
    assert service.history.latest_edit(TRIP) == previous


def test_unknown_public_hours_are_placed_saved_but_not_confirmed():
    client, _, repository, places, _ = setup_api()
    places.hours[("a", date(2026, 11, 14))] = None
    response = client.post(URL, json=body(item()))
    assert response.status_code == 200, response.text
    assert response.json()["generation"] == {"saved": True, "confirmed": False, "unplaced": []}
    assert "HOURS_NEEDS_CHECK" in {w["type"] for w in blocks(response.json())[0]["warnings"]}
    assert len(repository.get(TRIP).schedule.blocks) == 1


def test_closed_place_is_unplaced_without_a_default_time():
    client, _, repository, places, _ = setup_api()
    places.hours[("a", date(2026, 11, 14))] = OpeningHours(is_closed=True)
    response = client.post(URL, json=body(item()))
    assert response.status_code == 200, response.text
    assert not response.json()["generation"]["saved"]
    assert response.json()["generation"]["unplaced"][0]["reason"]["type"] == "CLOSED_DAY"
    assert repository.get(TRIP).schedule == ScheduleState()


def test_unavailable_route_does_not_fabricate_flexible_arrival_or_duration():
    client, _, repository, _, routes = setup_api()
    routes.duration = None
    routes.source = "UNKNOWN"
    response = client.post(URL, json=body(item("a"), item("b")))
    assert response.status_code == 200, response.text
    assert not response.json()["generation"]["saved"]
    assert response.json()["generation"]["unplaced"][0]["clientId"] == "selection-b"
    assert [block["place"]["id"] for block in blocks(response.json())] == ["a"]
    assert all(day["legs"] == [] for day in response.json()["days"])
    assert repository.get(TRIP).schedule == ScheduleState()


def test_fixed_times_with_unknown_route_can_save_without_confirmation():
    client, _, repository, _, routes = setup_api()
    routes.duration = None
    routes.source = "UNKNOWN"
    response = client.post(URL, json=body(pinned("a"), pinned("b", "12:00", "12:30")))
    assert response.status_code == 200, response.text
    assert response.json()["generation"] == {"saved": True, "confirmed": False, "unplaced": []}
    assert response.json()["days"][0]["legs"] == []
    assert repository.get(TRIP).schedule.legs[0].duration_min is None
    assert repository.get(TRIP).schedule.legs[0].source == "UNKNOWN"


def test_kakao_request_coordinates_never_reach_response_state_snapshot_or_logs(caplog):
    client, service, repository, _, _ = setup_api()
    response = client.post(URL, json=body(item("kakao", place=KAKAO, stayMin=30), item("public"), sessionCoords=COORDS))
    assert response.status_code == 200, response.text
    assert response.json()["generation"]["saved"]
    kakao = next(block for block in blocks(response.json()) if block["place"]["source"] == "KAKAO")
    assert kakao["place"] == {**KAKAO, "source": "KAKAO"}
    edited = client.patch(f"/api/trips/{TRIP}/blocks/{kakao['id']}", json={"stayMin": 35, "sessionCoords": COORDS})
    assert edited.status_code == 200, edited.text
    snapshot = service.history.latest_edit(TRIP)
    combined = (
        response.text + edited.text + repository.get(TRIP).schedule.model_dump_json() + repr(snapshot) + caplog.text
    )
    for secret in ("35.9876543", "129.9876543", "sessionCoords", "session_coords"):
        assert secret not in combined


def test_kakao_name_or_secret_in_invalid_input_is_not_echoed(caplog):
    client, _, repository, _, _ = setup_api()
    secret = "synthetic-private-search-and-key"
    response = client.post(URL, json=body(item("kakao", place={**KAKAO, "name": secret}), sessionCoords=COORDS))
    assert_error(response)
    assert secret not in response.text + caplog.text
    assert "35.9876543" not in response.text + caplog.text
    assert repository.get(TRIP).schedule == ScheduleState()


@pytest.mark.parametrize("write_first", [False, True])
def test_save_failure_restores_schedule_and_previous_edit(monkeypatch, write_first):
    client, service, repository, _, _ = setup_api()
    before = repository.get(TRIP)
    previous = service.history.record_before_edit(TRIP, before.schedule)
    original_save = repository.save
    first = True

    def fail_once(trip_id, record):
        nonlocal first
        if first:
            first = False
            if write_first:
                original_save(trip_id, record)
            raise RuntimeError("synthetic-secret-key-35.9876543")
        original_save(trip_id, record)

    monkeypatch.setattr(repository, "save", fail_once)
    response = client.post(URL, json=body(item()))
    assert_error(response, 503, "ERR-017")
    assert "synthetic-secret" not in response.text and "35.9876543" not in response.text
    assert repository.get(TRIP) == before
    assert service.history.latest_edit(TRIP) == previous


def test_discard_failure_restores_previous_edit_before_any_schedule_save(monkeypatch):
    client, service, repository, _, _ = setup_api()
    before = repository.get(TRIP)
    previous = service.history.record_before_edit(TRIP, before.schedule)
    original_discard = service.history.discard

    def fail_after_discard(trip_id):
        original_discard(trip_id)
        raise RuntimeError("synthetic-private-coordinates")

    monkeypatch.setattr(service.history, "discard", fail_after_discard)
    assert_error(client.post(URL, json=body(item())), 503, "ERR-017")
    assert repository.get(TRIP) == before
    assert service.history.latest_edit(TRIP) == previous


def test_generated_schedule_supports_edit_delete_undo_and_old_recompute_response():
    client, _, repository, _, _ = setup_api()
    generated = client.post(URL, json=body(pinned("a"), item("b")))
    assert generated.status_code == 200, generated.text
    flexible = next(b for b in blocks(generated.json()) if not b["isFixed"])
    block_url = f"/api/trips/{TRIP}/blocks/{flexible['id']}"
    edited = client.patch(block_url, json={"stayMin": 40})
    assert edited.status_code == 200, edited.text
    before_delete = repository.get(TRIP)
    deleted = client.delete(block_url)
    assert deleted.status_code == 200, deleted.text
    assert len(repository.get(TRIP).schedule.blocks) == 1
    restored = client.post(f"/api/trips/{TRIP}/undo")
    assert restored.status_code == 200, restored.text
    assert repository.get(TRIP) == before_delete
    recomputed = client.post(URL, json={})
    assert recomputed.status_code == 200, recomputed.text
    assert set(recomputed.json()) == {"days", "violations", "conflicts"}
    detail = client.get(f"/api/trips/{TRIP}")
    assert detail.status_code == 200
    assert {b["id"] for b in blocks(detail.json()["schedule"])} == {b.id for b in before_delete.schedule.blocks}


def test_default_service_wires_initial_planner_without_external_keys():
    with TestClient(create_app()) as client:
        created = client.post(
            "/api/trips",
            json={
                "dates": {"start": "2026-11-17", "end": "2026-11-17"},
                "dayStart": "09:00",
                "dayEnd": "20:00",
                "mode": "TRANSIT",
            },
        )
        assert created.status_code == 201
        trip_id = created.json()["tripId"]
        response = client.post(f"/api/trips/{trip_id}/schedule", json=body(item("126848")))
        assert response.status_code == 200, response.text
        assert response.json()["generation"]["saved"]
        assert blocks(response.json())[0]["stayMin"] == 60
        assert client.get(f"/api/trips/{trip_id}").json()["schedule"]["days"][0]["blocks"]


def test_reversed_fixed_day_order_is_rejected_without_saving():
    client, service, repository, _, _ = setup_api(days=2)
    before = repository.get(TRIP)
    previous = service.history.record_before_edit(TRIP, before.schedule)
    response = client.post(
        URL,
        json=body(
            item("a", fixedWindow={"dayNo": 2, "start": "10:00", "end": "10:30"}),
            pinned("b", "12:00", "12:30"),
        ),
    )
    assert_error(response, 409, "ERR-009")
    assert repository.get(TRIP) == before
    assert service.history.latest_edit(TRIP) == previous


def test_missing_public_projection_is_unavailable_not_a_saved_partial_record():
    client, service, repository, places, _ = setup_api()
    before = repository.get(TRIP)
    previous = service.history.record_before_edit(TRIP, before.schedule)
    places.incomplete.add("a")
    assert_error(client.post(URL, json=body(item())), 503, "ERR-017")
    assert repository.get(TRIP) == before
    assert service.history.latest_edit(TRIP) == previous


def test_missing_kakao_coordinates_do_not_trigger_route_calls_or_invent_values():
    client, _, repository, _, routes = setup_api()
    response = client.post(
        URL,
        json=body(
            pinned("kakao", place=KAKAO),
            pinned("public", "12:00", "12:30"),
        ),
    )
    assert response.status_code == 200, response.text
    assert response.json()["generation"] == {"saved": True, "confirmed": False, "unplaced": []}
    assert routes.departures == []
    assert response.json()["days"][0]["legs"] == []
    assert repository.get(TRIP).schedule.legs[0].duration_min is None


def test_kakao_without_coordinates_skips_overlapping_pin_and_uses_next_day():
    client, _, repository, _, routes = setup_api(days=2)
    response = client.post(
        URL,
        json=body(
            pinned("public", "10:00", "10:30"),
            item("kakao", place=KAKAO, stayMin=90),
        ),
    )

    assert response.status_code == 200, response.text
    assert response.json()["generation"] == {"saved": True, "confirmed": False, "unplaced": []}
    values = blocks(response.json())
    assert [(value["place"]["source"], value["dayNo"], value["arriveAt"]) for value in values] == [
        ("PUBLIC", 1, "10:00"),
        ("KAKAO", 2, "09:00"),
    ]
    assert routes.departures == []
    assert len(repository.get(TRIP).schedule.blocks) == 2


def test_route_exception_does_not_echo_provider_secrets(caplog, monkeypatch):
    client, _, repository, _, routes = setup_api()
    secret = "synthetic-api-key-35.9876543"

    def fail(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(routes, "estimate_at", fail)
    response = client.post(URL, json=body(pinned("a"), pinned("b", "12:00", "12:30")))
    assert response.status_code == 200, response.text
    assert not response.json()["generation"]["confirmed"]
    assert secret not in response.text + caplog.text + repository.get(TRIP).schedule.model_dump_json()


def test_default_initial_request_does_not_guess_unknown_kakao_stay():
    with TestClient(create_app()) as client:
        created = client.post(
            "/api/trips",
            json={
                "dates": {"start": "2026-11-17", "end": "2026-11-17"},
                "dayStart": "09:00",
                "dayEnd": "20:00",
                "mode": "TRANSIT",
            },
        )
        trip_id = created.json()["tripId"]
        response = client.post(f"/api/trips/{trip_id}/schedule", json=body(item("kakao", place=KAKAO)))
        assert response.status_code == 200, response.text
        assert not response.json()["generation"]["saved"]
        assert response.json()["generation"]["unplaced"][0]["reason"]["type"] == "STAY_NEEDS_CHECK"
        assert client.get(f"/api/trips/{trip_id}").json()["schedule"]["days"][0]["blocks"] == []


def test_known_visit_overlap_is_not_saved_when_route_is_unknown():
    client, service, repository, _, routes = setup_api()
    routes.duration = None
    routes.source = "UNKNOWN"
    before = repository.get(TRIP)
    previous = service.history.record_before_edit(TRIP, before.schedule)
    response = client.post(URL, json=body(pinned("a", "09:00", "09:30"), item("b")))
    assert response.status_code == 200, response.text
    assert response.json()["generation"]["saved"] is False
    assert response.json()["generation"]["unplaced"] == [
        {
            "clientId": "selection-b",
            "reason": {
                "type": "FIXED_ORDER_CONFLICT",
                "cause": "입력 순서에서 고정 방문시간을 지킬 수 없습니다.",
            },
        }
    ]
    assert repository.get(TRIP) == before
    assert service.history.latest_edit(TRIP) == previous
