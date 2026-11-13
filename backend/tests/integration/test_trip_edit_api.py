"""API-007(PATCH)·API-008(DELETE)·API-010(undo) HTTP 계약: 상태 코드·오류 ID·no-store·입력 비노출."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.unit.trips.test_service_edits import TRIP, saved, setup_service

BLOCKS = f"/api/trips/{TRIP}/blocks"
UNDO = f"/api/trips/{TRIP}/undo"
SECRET = "synthetic-kakao-name-35.1234567"


def setup_api():
    service, repository, routes = setup_service()
    return TestClient(create_app(trip_service=service)), repository, routes


def assert_error(response, status: int, error_id: str) -> None:
    assert response.status_code == status
    assert response.json()["error"]["id"] == error_id
    assert response.headers["cache-control"] == "no-store"


def test_patch_stay_returns_mutation_and_undo_restores_schedule():
    client, repository, _ = setup_api()
    before = saved(repository)
    original = client.post(f"/api/trips/{TRIP}/schedule", json={}).json()

    response = client.patch(f"{BLOCKS}/b", json={"stayMin": 60})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert set(payload) == {"schedule", "violations"}
    blocks = payload["schedule"]["days"][0]["blocks"]
    assert [(b["id"], b["seq"]) for b in blocks] == [("a", 1), ("b", 2), ("c", 3), ("f", 4), ("g", 5)]
    assert (blocks[1]["arriveAt"], blocks[1]["departAt"], blocks[1]["stayMin"]) == ("09:45", "10:45", 60)

    undone = client.post(UNDO)
    assert undone.status_code == 200
    assert undone.headers["cache-control"] == "no-store"
    assert set(undone.json()) == {"schedule"}
    assert undone.json()["schedule"]["days"] == original["days"]
    assert saved(repository) == before
    assert_error(client.post(UNDO), 409, "ERR-001")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"seq": 3}, [("a", 1), ("c", 2), ("b", 3), ("f", 4), ("g", 5)]),
        ({"isFixed": False}, [("a", 1), ("b", 2), ("c", 3), ("f", 4), ("g", 5)]),
    ],
)
def test_patch_seq_and_is_fixed(body, expected):
    client, _, _ = setup_api()
    target = "b" if "seq" in body else "a"
    response = client.patch(f"{BLOCKS}/{target}", json=body)
    assert response.status_code == 200
    blocks = response.json()["schedule"]["days"][0]["blocks"]
    assert [(b["id"], b["seq"]) for b in blocks] == expected
    if "isFixed" in body:
        assert (blocks[0]["isFixed"], blocks[0]["fixedStart"], blocks[0]["arriveAt"]) == (False, None, "09:00")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"sessionCoords": {}},
        {"seq": 2, "stayMin": 40},
        {"isFixed": True, "seq": 1},
        {"stayMin": 0},
        {"seq": 0},
        {"isFixed": None},
        {"stayMin": 40, "unknown": 1},
    ],
)
def test_patch_requires_exactly_one_valid_change(body):
    client, repository, _ = setup_api()
    before = saved(repository)
    assert_error(client.patch(f"{BLOCKS}/b", json=body), 400, "ERR-001")
    assert saved(repository) == before


@pytest.mark.parametrize(
    ("trip", "block", "body", "status", "error_id"),
    [
        (TRIP, "missing", {"stayMin": 40}, 400, "ERR-001"),
        (TRIP, "b", {"seq": 9}, 400, "ERR-001"),
        (TRIP, "b", {"isFixed": True}, 400, "ERR-001"),
        (TRIP, "b", {"seq": 1}, 409, "ERR-009"),
        (TRIP, "a", {"stayMin": 60}, 409, "ERR-009"),
        ("missing", "b", {"stayMin": 40}, 404, "ERR-016"),
    ],
)
def test_patch_errors_keep_state(trip, block, body, status, error_id):
    client, repository, _ = setup_api()
    before = saved(repository)
    assert_error(client.patch(f"/api/trips/{trip}/blocks/{block}", json=body), status, error_id)
    assert saved(repository) == before


def test_delete_without_body_and_with_session_coords(caplog):
    client, repository, _ = setup_api()

    response = client.delete(f"{BLOCKS}/c")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert set(response.json()) == {"schedule", "violations"}
    assert [b["id"] for b in response.json()["schedule"]["days"][0]["blocks"]] == ["a", "b", "f", "g"]

    coords = {"sessionCoords": {"123": {"lat": 35.1234567, "lng": 129.7654321}}}
    response = client.request("DELETE", f"{BLOCKS}/e", json=coords)
    assert response.status_code == 200
    assert [b["id"] for b in response.json()["schedule"]["days"][1]["blocks"]] == ["d"]
    for secret in ("35.1234567", "129.7654321", "sessionCoords"):
        assert secret not in response.text + caplog.text + saved(repository).model_dump_json()


@pytest.mark.parametrize(
    ("trip", "block", "status", "error_id"),
    [(TRIP, "missing", 400, "ERR-001"), ("missing", "b", 404, "ERR-016")],
)
def test_delete_errors_keep_state(trip, block, status, error_id):
    client, repository, _ = setup_api()
    before = saved(repository)
    assert_error(client.delete(f"/api/trips/{trip}/blocks/{block}"), status, error_id)
    assert saved(repository) == before


def test_undo_reverts_delete_and_accepts_session_coords_body():
    client, repository, _ = setup_api()
    before = saved(repository)
    assert client.delete(f"{BLOCKS}/b").status_code == 200

    response = client.post(UNDO, json={"sessionCoords": {"123": {"lat": 35.1234567, "lng": 129.7654321}}})

    assert response.status_code == 200
    assert [b["id"] for b in response.json()["schedule"]["days"][0]["blocks"]] == ["a", "b", "c", "f", "g"]
    assert "35.1234567" not in response.text
    assert saved(repository) == before


def test_undo_without_history_or_trip():
    client, repository, _ = setup_api()
    before = saved(repository)
    response = client.post(UNDO)
    assert_error(response, 409, "ERR-001")
    assert "되돌릴" in response.json()["error"]["message"]
    assert_error(client.post("/api/trips/missing/undo"), 404, "ERR-016")
    assert saved(repository) == before


@pytest.mark.parametrize(
    ("method", "path", "extra"),
    [("PATCH", f"{BLOCKS}/b", {"stayMin": 40}), ("DELETE", f"{BLOCKS}/b", {}), ("POST", UNDO, {})],
)
def test_invalid_session_coords_are_not_echoed(method, path, extra, caplog):
    client, repository, _ = setup_api()
    before = saved(repository)
    body = {**extra, "sessionCoords": {"123": {"lat": SECRET, "lng": 129.7654321, "name": SECRET}}}
    response = client.request(method, path, json=body)
    assert_error(response, 400, "ERR-001")
    assert SECRET not in response.text + caplog.text
    assert "129.7654321" not in response.text + caplog.text
    assert saved(repository) == before
