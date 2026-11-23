"""FR-008 예상 혼잡 API 통합 테스트."""

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
