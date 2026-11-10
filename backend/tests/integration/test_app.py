from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from app.core.config import Settings
from app.main import create_app
from app.modules.trips.schemas import Schedule, ScheduleDay


def test_health_and_openapi(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Backend test"
    assert "/api/health" in response.json()["paths"]
    assert "/api/trips/{trip_id}/schedule" in response.json()["paths"]
    # Endpoints exist, but production providers must be explicitly configured.
    assert client.post("/api/trips/test/schedule", json={}).status_code == 503


def test_explicit_settings_override_environment(monkeypatch) -> None:
    monkeypatch.setenv("PINANDFILL_APP_NAME", "Environment name")
    assert create_app().title == "Environment name"
    assert create_app(Settings(app_name="Explicit name")).title == "Explicit name"


def test_validation_does_not_echo_or_log_search_data(caplog) -> None:
    class Input(BaseModel):
        model_config = ConfigDict(extra="forbid")
        count: int

    application = create_app(Settings())

    @application.post("/test-only-input")
    def receive(body: Input) -> dict[str, int]:
        return {"count": body.count}

    secret = "synthetic-kakao-name-35.123456"
    with TestClient(application) as client:
        response = client.post("/test-only-input", json={"count": secret, "name": secret})
    assert response.status_code == 400
    assert response.json()["error"]["id"] == "ERR-001"
    assert response.headers["cache-control"] == "no-store"
    assert secret not in response.text
    assert secret not in caplog.text


def test_schedule_response_serializes_through_fastapi() -> None:
    from datetime import date

    application = create_app(Settings())

    @application.get("/test-only-schedule", response_model=Schedule)
    def schedule() -> Schedule:
        return Schedule(days=(ScheduleDay(day_no=1, date=date(2026, 11, 2)),))

    with TestClient(application) as client:
        response = client.get("/test-only-schedule")
    assert response.status_code == 200
    assert response.json() == {
        "days": [{"dayNo": 1, "date": "2026-11-02", "blocks": [], "legs": [], "crowd": [], "weather": []}],
        "violations": [],
        "conflicts": [],
    }
