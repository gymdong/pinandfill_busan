"""FR-008 예상 혼잡 API 통합 테스트. tests/fixtures/crowd 는 시험용 가짜 값이다."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_crowd_api_returns_unknown_when_no_data():
    """혼잡 데이터가 없으면 임의의 예측값을 만들지 않는다."""
    app = create_app(Settings(app_name="Backend test"))

    with TestClient(app) as client:
        response = client.get(
            "/api/places/126078/crowd",
            params={"date": "2026-11-24"},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "hours": [],
        "confidence": "없음",
        "asOf": None,
        "sources": [],
        "signals": [],
    }


def test_crowd_api_rejects_invalid_date():
    """잘못된 날짜 형식은 거부한다."""
    app = create_app(Settings(app_name="Backend test"))

    with TestClient(app) as client:
        response = client.get(
            "/api/places/126078/crowd",
            params={"date": "invalid-date"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["id"] == "ERR-001"


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "crowd"


@pytest.fixture
def fixture_client(monkeypatch: pytest.MonkeyPatch):
    """시험용 표본 디렉터리를 CROWD_DATA_DIR 로 주입한 기본 구성 앱(표본 장소 주소로 구·군을 찾는다)."""
    monkeypatch.setenv("CROWD_DATA_DIR", str(FIXTURES))
    with TestClient(create_app(Settings(app_name="Backend test"))) as client:
        yield client


def test_crowd_api_with_fixture_inputs(fixture_client):
    # 태종대유원지(영도구): DATA-04 + DATA-05 + 영도구 2026-11-28 날짜 배수 → 신호 3개
    response = fixture_client.get("/api/places/126658/crowd", params={"date": "2026-11-28"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["confidence"] == "높음"
    assert [hour["h"] for hour in body["hours"]] == list(range(9, 18))
    assert all(hour["grade"] in {"여유", "보통", "붐빔", "매우 붐빔"} for hour in body["hours"])
    assert all(0 <= hour["score"] <= 1 for hour in body["hours"])
    assert body["asOf"] == "2026-11-24T06:00:00+09:00"
    assert len(body["sources"]) == 3
    assert [signal["source"] for signal in body["signals"]] == ["DATA-04", "DATA-05", "DATA-06"]
    assert set(body["signals"][0]) == {"source", "label", "refPeriod", "detail"}


def test_crowd_api_confidence_follows_available_signals(fixture_client):
    # 날짜 배수가 없는 날은 신호 2개
    assert fixture_client.get("/api/places/126658/crowd", params={"date": "2026-11-27"}).json()["confidence"] == "중간"
    # 광안리해수욕장(수영구): DATA-04 만
    assert fixture_client.get("/api/places/126078/crowd", params={"date": "2026-11-25"}).json()["confidence"] == "낮음"


@pytest.mark.parametrize("place_id", ["999999", "1234567890", "130166"])
def test_unknown_kakao_or_unlinked_place_is_no_information(fixture_client, place_id):
    """모르는 ID·카카오 장소 ID·연결 없는 공공 장소는 200 + 정보 부족(ERR-011)."""
    response = fixture_client.get(f"/api/places/{place_id}/crowd", params={"date": "2026-11-28"})
    assert response.status_code == 200
    assert response.json() == {"hours": [], "confidence": "없음", "asOf": None, "sources": [], "signals": []}


def test_empty_data_directory_is_no_information(monkeypatch, tmp_path):
    monkeypatch.setenv("CROWD_DATA_DIR", str(tmp_path))
    with TestClient(create_app(Settings(app_name="Backend test"))) as client:
        body = client.get("/api/places/126658/crowd", params={"date": "2026-11-28"}).json()
    assert body["confidence"] == "없음" and body["hours"] == []


def test_production_directory_has_no_test_fixture_files():
    """시험용 가짜 표본이 운영 경로 data/crowd/ 로 들어가지 않았는지 확인한다."""
    production = Path(__file__).resolve().parents[3] / "data" / "crowd"
    for path in production.glob("*.csv"):
        assert "TEST-" not in path.read_text(encoding="utf-8-sig"), path.name
