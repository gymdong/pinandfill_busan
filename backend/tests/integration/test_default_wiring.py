"""서비스를 주입하지 않은 create_app() 의 기본 구성. 키는 conftest 가 비워 두어 외부 API 를 부르지 않는다."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.places.service import PlaceSearchService

TRIP = {
    "dates": {"start": "2026-11-17", "end": "2026-11-17"},
    "dayStart": "09:00",
    "dayEnd": "20:00",
    "mode": "TRANSIT",
}
# 표본 data/samples 의 공공 장소(해동용궁사·부산시립미술관)와 해동용궁사의 카카오 매칭 ID
FIXED = {
    "dayNo": 1,
    "place": {"placeId": "126848"},
    "isFixed": True,
    "fixedWindow": {"dayNo": 1, "start": "09:00", "end": "10:00"},
    "origin": "USER",
}
MUSEUM = {"dayNo": 1, "place": {"placeId": "130166"}, "isFixed": False, "origin": "USER"}


def blocks(response) -> list[dict]:
    return response.json()["schedule"]["days"][0]["blocks"]


def test_trip_edit_flow_without_injected_services():
    with TestClient(create_app()) as client:
        created = client.post("/api/trips", json=TRIP)
        assert created.status_code == 201
        trip_id = created.json()["tripId"]

        first = client.post(f"/api/trips/{trip_id}/blocks", json=FIXED)
        assert first.status_code == 200
        added = client.post(f"/api/trips/{trip_id}/blocks", json=MUSEUM)
        assert added.status_code == 200
        fixed, museum = blocks(added)
        assert fixed["place"]["name"] == "해동용궁사" and fixed["stayMin"] == 60
        # 체류시간은 표본 값, 화요일 영업시간이 있어 HOURS_NEEDS_CHECK 가 없다.
        assert museum["stayMin"] == 90
        types = {warning["type"] for warning in museum["warnings"]}
        assert "HOURS_NEEDS_CHECK" not in types
        # 경로 키가 없으면 이동시간을 만들지 않는다: 구간은 빠지고 '확인 필요' 경고가 붙는다.
        assert "TRAVEL_TIME_NEEDS_CHECK" in types
        assert added.json()["schedule"]["days"][0]["legs"] == []
        assert museum["arriveAt"] is None

        patched = client.patch(f"/api/trips/{trip_id}/blocks/{museum['id']}", json={"stayMin": 45})
        assert patched.status_code == 200
        assert blocks(patched)[1]["stayMin"] == 45

        deleted = client.delete(f"/api/trips/{trip_id}/blocks/{museum['id']}")
        assert deleted.status_code == 200
        assert [block["id"] for block in blocks(deleted)] == [fixed["id"]]

        undone = client.post(f"/api/trips/{trip_id}/undo")
        assert undone.status_code == 200
        restored = undone.json()["schedule"]["days"][0]["blocks"]
        assert [(block["id"], block["stayMin"]) for block in restored] == [(fixed["id"], 60), (museum["id"], 45)]


def test_kakao_block_uses_matched_sample_stay_and_rejects_unknown():
    with TestClient(create_app()) as client:
        trip_id = client.post("/api/trips", json=TRIP).json()["tripId"]
        matched = {"kakaoPlaceId": "8606230", "placeUrl": "https://place.map.kakao.com/8606230"}
        response = client.post(f"/api/trips/{trip_id}/blocks", json={**FIXED, "place": matched, "sessionCoords": {}})
        assert response.status_code == 200
        block = blocks(response)[0]
        # 카카오 블록에는 ID·URL 만 남고 이름·좌표는 응답·저장에 없다.
        assert block["place"] == {**matched, "source": "KAKAO"} and block["stayMin"] == 60

        unknown = {"kakaoPlaceId": "900000009", "placeUrl": "https://place.map.kakao.com/900000009"}
        response = client.post(f"/api/trips/{trip_id}/blocks", json={**FIXED, "place": unknown})
        assert response.status_code == 400
        unknown_public = client.post(f"/api/trips/{trip_id}/blocks", json={**MUSEUM, "place": {"placeId": "999"}})
        assert unknown_public.status_code == 400


def test_place_search_is_enabled_only_with_a_kakao_key(monkeypatch: pytest.MonkeyPatch):
    assert create_app().state.place_search_service is None
    monkeypatch.setenv("KAKAO_REST_API_KEY", "test-rest-key")
    # 만들기만 하고 카카오를 부르지 않는다.
    assert isinstance(create_app().state.place_search_service, PlaceSearchService)
