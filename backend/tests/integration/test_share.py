"""FR-011 읽기 전용 공유(API-019·020): 추측 불가 토큰, 만료, 여행 ID 비노출, 저장된 일정 그대로."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.share.repository import InMemoryShareLinks, token_digest

TRIP = {"dates": {"start": "2026-12-02", "end": "2026-12-02"}, "dayStart": "09:00", "dayEnd": "20:00", "mode": "WALK"}
BLOCK = {
    "dayNo": 1,
    "place": {"placeId": "126121"},
    "isFixed": True,
    "fixedWindow": {"dayNo": 1, "start": "10:00", "end": "11:00"},
    "stayMin": 60,
    "origin": "USER",
}


def _trip(client: TestClient) -> str:
    trip_id = client.post("/api/trips", json=TRIP).json()["tripId"]
    assert client.post(f"/api/trips/{trip_id}/blocks", json=BLOCK).status_code == 200
    return trip_id


def test_shared_link_shows_schedule_read_only_without_trip_id() -> None:
    with TestClient(create_app()) as client:
        trip_id = _trip(client)
        created = client.post(f"/api/trips/{trip_id}/share")
        assert created.status_code == 200, created.text
        body = created.json()
        shared = client.get(f"/api/shared/{body['token']}")
        detail = client.get(f"/api/trips/{trip_id}").json()
    assert body["url"] == f"/shared/{body['token']}"
    assert len(body["token"]) >= 40
    assert shared.status_code == 200
    assert shared.headers["Cache-Control"] == "no-store"
    data = shared.json()
    assert data["schedule"] == detail["schedule"]
    assert data["trip"]["mode"] == "WALK" and data["trip"]["dates"]["start"] == "2026-12-02"
    # 여행 ID 가 새면 편집 API 를 부를 수 있다. 공유 응답 어디에도 넣지 않는다.
    assert trip_id not in shared.text
    assert "canUndo" not in data


def test_links_are_unguessable_and_expire() -> None:
    with TestClient(create_app()) as client:
        trip_id = _trip(client)
        first = client.post(f"/api/trips/{trip_id}/share").json()["token"]
        second = client.post(f"/api/trips/{trip_id}/share").json()["token"]
        past = client.post(
            f"/api/trips/{trip_id}/share", json={"expiresAt": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()}
        )
        missing_trip = client.post("/api/trips/00000000-0000-4000-8000-000000000000/share")
        unknown = client.get("/api/shared/" + "a" * 43)
        malformed = client.get("/api/shared/short")
    assert first != second
    assert past.status_code == 400
    assert missing_trip.status_code == 404
    assert unknown.status_code == 404 and unknown.json()["error"]["id"] == "ERR-016"
    assert malformed.status_code == 404 and malformed.json()["error"]["id"] == "ERR-016"


def test_expired_link_is_not_found_and_only_digest_is_stored() -> None:
    links = InMemoryShareLinks()
    app = create_app()
    with TestClient(app) as client:
        service = app.state.share_service
        service.links = links
        trip_id = _trip(client)
        soon = datetime.now(UTC) + timedelta(hours=1)
        token = client.post(f"/api/trips/{trip_id}/share", json={"expiresAt": soon.isoformat()}).json()["token"]
        assert client.get(f"/api/shared/{token}").status_code == 200
        service.clock = lambda: soon + timedelta(seconds=1)
        expired = client.get(f"/api/shared/{token}")
    assert expired.status_code == 404
    assert links.find(token) is None and links.find(token_digest(token)) is not None


def test_links_without_expiry_close_a_week_after_the_trip() -> None:
    with TestClient(create_app()) as client:
        trip_id = _trip(client)
        body = client.post(f"/api/trips/{trip_id}/share").json()
    # 2026-12-02 당일 여행 → 12-03 00:00 KST + 7일 = 2026-12-09T15:00:00Z
    assert body["expiresAt"].startswith("2026-12-09T15:00:00")
