"""서비스를 주입하지 않은 create_app() 의 기본 구성. 키는 conftest 가 비워 두어 외부 API 를 부르지 않는다."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.adapters.kakao import KakaoSettings
from app.main import create_app, kakao_settings
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
        # 경로 키가 없으면 좌표로 추정한다: 구간은 '추정'(ESTIMATED)이고 도착 시각이 생긴다.
        # 구간 표시가 이미 '추정'이라 블록마다 같은 뜻의 경고(ROUTE_TIME_CONTEXT_ONLY)를 붙이지 않는다.
        assert "TRAVEL_TIME_NEEDS_CHECK" not in types
        assert "ROUTE_TIME_CONTEXT_ONLY" not in types
        (leg,) = added.json()["schedule"]["days"][0]["legs"]
        assert leg["source"] == "ESTIMATED" and leg["durationMin"] > 0
        assert museum["arriveAt"] is not None

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


def test_get_trip_returns_conditions_and_projected_schedule():
    with TestClient(create_app()) as client:
        missing = client.get("/api/trips/missing")
        assert missing.status_code == 404 and missing.json()["error"]["id"] == "ERR-016"
        trip_id = client.post("/api/trips", json=TRIP).json()["tripId"]
        empty = client.get(f"/api/trips/{trip_id}")
        assert empty.status_code == 200 and empty.headers["cache-control"] == "no-store"
        assert empty.json()["trip"] == {
            "id": trip_id,
            "dates": {"start": "2026-11-17", "end": "2026-11-17"},
            "dayStart": "09:00",
            "dayEnd": "20:00",
            "mode": "TRANSIT",
            "detourThresholdMin": 15,
        }
        assert empty.json()["canUndo"] is False
        added = client.post(f"/api/trips/{trip_id}/blocks", json=FIXED).json()["schedule"]
        loaded = client.get(f"/api/trips/{trip_id}").json()
        detail = loaded["schedule"]
        assert [b["id"] for b in detail["days"][0]["blocks"]] == [b["id"] for b in added["days"][0]["blocks"]]
        # 화면을 다시 열어도 되돌리기를 켤 수 있게 서버가 알려 준다(FR-006).
        assert loaded["canUndo"] is True
        assert client.post(f"/api/trips/{trip_id}/undo").status_code == 200
        assert client.get(f"/api/trips/{trip_id}").json()["canUndo"] is False


def test_kakao_block_uses_matched_sample_stay_and_rejects_unknown():
    with TestClient(create_app()) as client:
        trip_id = client.post("/api/trips", json=TRIP).json()["tripId"]
        matched = {"kakaoPlaceId": "8606230", "placeUrl": "https://place.map.kakao.com/8606230"}
        response = client.post(f"/api/trips/{trip_id}/blocks", json={**FIXED, "place": matched, "sessionCoords": {}})
        assert response.status_code == 200
        block = blocks(response)[0]
        # 카카오 블록에는 ID·URL 만 남고 이름·좌표는 응답·저장에 없다.
        assert block["place"] == {**matched, "source": "KAKAO"} and block["stayMin"] == 60

        # API-026 조회도 좌표 없이 카카오 블록을 ID·URL 로만 돌려준다.
        detail = client.get(f"/api/trips/{trip_id}")
        assert detail.status_code == 200
        assert detail.json()["schedule"]["days"][0]["blocks"][0]["place"] == {**matched, "source": "KAKAO"}

        unknown = {"kakaoPlaceId": "900000009", "placeUrl": "https://place.map.kakao.com/900000009"}
        response = client.post(f"/api/trips/{trip_id}/blocks", json={**FIXED, "place": unknown})
        assert response.status_code == 400
        unknown_public = client.post(f"/api/trips/{trip_id}/blocks", json={**MUSEUM, "place": {"placeId": "999"}})
        assert unknown_public.status_code == 400


def test_place_search_is_enabled_only_with_a_kakao_key(monkeypatch: pytest.MonkeyPatch):
    with TestClient(create_app()) as client:
        assert client.app.state.place_search_service is None
    monkeypatch.setenv("KAKAO_REST_API_KEY", "test-rest-key")
    application = create_app()
    # 카카오 클라이언트는 lifespan 안에서만 열리고, 끝나면 서비스도 함께 내려간다. 카카오를 부르지 않는다.
    assert application.state.place_search_service is None
    with TestClient(application):
        assert isinstance(application.state.place_search_service, PlaceSearchService)
    assert application.state.place_search_service is None


def test_missing_kakao_key_only_disables_search(monkeypatch: pytest.MonkeyPatch):
    # 키 환경변수가 아예 없어도(빈 값이 아니라) 예외 없이 '검색 꺼짐'(None)이다. 로컬 .env 는 읽지 않는다.
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    monkeypatch.setattr("app.main.KakaoSettings", lambda: KakaoSettings(_env_file=None))
    assert kakao_settings() is None


def test_missing_key_and_bad_setting_together_still_fail_at_startup(monkeypatch: pytest.MonkeyPatch):
    # 키가 없어도 다른 설정 오류가 함께 있으면 '검색 꺼짐'으로 덮지 않고 시작할 때 드러낸다(#34 리뷰).
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    monkeypatch.setenv("KAKAO_SEARCH_RECT", "129.32,34.86,128.74,35.40")
    monkeypatch.setattr("app.main.KakaoSettings", lambda: KakaoSettings(_env_file=None))
    with pytest.raises(ValidationError) as error:
        kakao_settings()
    assert {item["loc"] for item in error.value.errors()} == {("rest_api_key",), ("search_rect",)}


def test_bad_kakao_setting_fails_at_startup_instead_of_disabling_search(monkeypatch: pytest.MonkeyPatch):
    # 키가 아닌 설정 오류는 검색을 조용히 끄지 않고 시작할 때 드러낸다.
    monkeypatch.setenv("KAKAO_REST_API_KEY", "test-rest-key")
    monkeypatch.setenv("KAKAO_SEARCH_RECT", "129.32,34.86,128.74,35.40")
    with pytest.raises(ValidationError):
        create_app()


KAKAO_UNKNOWN = {"kakaoPlaceId": "900000009", "placeUrl": "https://place.map.kakao.com/900000009"}


def test_kakao_block_without_stay_source_asks_for_stay_min():
    with TestClient(create_app()) as client:
        trip_id = client.post("/api/trips", json=TRIP).json()["tripId"]
        response = client.post(f"/api/trips/{trip_id}/blocks", json={**FIXED, "place": KAKAO_UNKNOWN})
        assert response.status_code == 400
        error = response.json()["error"]
        assert error["id"] == "ERR-001" and error["fields"] == {"stayMin": error["message"]}
        # 아무것도 저장되지 않았다.
        assert client.get(f"/api/trips/{trip_id}").json()["schedule"]["days"][0]["blocks"] == []


def test_user_stay_min_comes_before_public_value():
    with TestClient(create_app()) as client:
        trip_id = client.post("/api/trips", json=TRIP).json()["tripId"]
        window = FIXED["fixedWindow"]
        length = _minutes(window["end"]) - _minutes(window["start"])
        kakao = client.post(f"/api/trips/{trip_id}/blocks", json={**FIXED, "place": KAKAO_UNKNOWN, "stayMin": length})
        assert kakao.status_code == 200
        assert blocks(kakao)[0]["stayMin"] == length
        museum = client.post(f"/api/trips/{trip_id}/blocks", json={**MUSEUM, "stayMin": 30})
        assert museum.status_code == 200
        # 표본 값(90)이 있어도 사용자 값이 먼저다.
        assert blocks(museum)[1]["stayMin"] == 30


@pytest.mark.parametrize("stay", [0, 1441, "45", True, None])
def test_add_block_rejects_invalid_stay_min(stay):
    with TestClient(create_app()) as client:
        trip_id = client.post("/api/trips", json=TRIP).json()["tripId"]
        body = {**MUSEUM, "stayMin": stay}
        response = client.post(f"/api/trips/{trip_id}/blocks", json=body)
        if stay is None:
            # 보내지 않은 것과 같다: 표본 값을 쓴다.
            assert response.status_code == 200 and blocks(response)[0]["stayMin"] == 90
        else:
            assert response.status_code == 400 and "fields" not in response.json()["error"]


def test_add_block_rejects_stay_min_different_from_fixed_window():
    with TestClient(create_app()) as client:
        trip_id = client.post("/api/trips", json=TRIP).json()["tripId"]
        window = FIXED["fixedWindow"]
        length = _minutes(window["end"]) - _minutes(window["start"])
        response = client.post(f"/api/trips/{trip_id}/blocks", json={**FIXED, "stayMin": length + 10})
        assert response.status_code == 400
        assert client.get(f"/api/trips/{trip_id}").json()["schedule"]["days"][0]["blocks"] == []


def _minutes(value: str) -> int:
    hour, minute = value.split(":")[:2]
    return int(hour) * 60 + int(minute)
