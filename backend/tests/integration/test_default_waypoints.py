"""기본 구성(create_app())의 경유지 제안(FR-004): 앱의 공공 장소가 후보이고, 넣은 시각의 예상 혼잡이 붙는다.

경로는 고정 20분 가짜, 혼잡은 tests/fixtures/crowd(시험용 가짜 값)다.
"""

import shutil
from datetime import UTC, datetime, time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.crowd.schemas import CrowdHour, PlaceCrowdResponse
from app.modules.engine.interfaces import RouteEstimate
from app.modules.recommend.waypoints import PublicPlaceCandidates, ScoreWeights, crowd_at_stay

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "crowd"
# 2026-12-02(수). 용두산 공원 → 부산시립미술관(둘 다 고정)
TRIP = {
    "dates": {"start": "2026-12-02", "end": "2026-12-02"},
    "dayStart": "09:00",
    "dayEnd": "20:00",
    "mode": "TRANSIT",
}


class TwentyMinutes:
    def estimate(self, origin: object, destination: object, *, mode: str) -> RouteEstimate:
        return RouteEstimate(20, "ESTIMATED", datetime(2026, 12, 1, tzinfo=UTC))


def fixed(place_id: str, start: str, end: str, stay: int) -> dict[str, object]:
    window = {"dayNo": 1, "start": start, "end": end}
    place = {"placeId": place_id}
    return {"dayNo": 1, "place": place, "isFixed": True, "fixedWindow": window, "stayMin": stay, "origin": "USER"}


def test_default_app_suggests_public_places_with_crowd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # 시험용 혼잡 표본을 복사하고, 영업시간이 확인된 후보 범어사(126148)에 시험용 행정동을 잇는다.
    crowd_dir = tmp_path / "crowd"
    shutil.copytree(FIXTURES, crowd_dir)
    with (crowd_dir / "place_signal_links.csv").open("a", encoding="utf-8") as links:
        links.write("126148,DATA-04,TEST-DONG-1,시험용 연결(범어사)\n")
    monkeypatch.setattr("app.main.build_route_provider", TwentyMinutes)
    monkeypatch.setenv("CROWD_DATA_DIR", str(crowd_dir))
    flat = ScoreWeights(preference=0, representativeness=0, detour=1, crowd=0, missing_crowd_penalty=0)
    monkeypatch.setattr("app.main.WAYPOINT_WEIGHTS", flat)
    monkeypatch.setattr("app.main.WAYPOINT_ROUTE_CANDIDATES", None)
    with TestClient(create_app()) as client:
        trip_id = client.post("/api/trips", json=TRIP).json()["tripId"]
        one = client.post(f"/api/trips/{trip_id}/blocks", json=fixed("126121", "10:00", "11:00", 60))
        assert one.status_code == 200, one.text
        added = client.post(f"/api/trips/{trip_id}/blocks", json=fixed("130166", "15:00", "16:30", 90))
        assert added.status_code == 200, added.text
        first, second = (block["id"] for block in added.json()["schedule"]["days"][0]["blocks"])
        response = client.post(
            f"/api/trips/{trip_id}/waypoints/suggest",
            json={"fromBlockId": first, "toBlockId": second, "thresholdMin": 30},
        )
    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert 1 <= len(candidates) <= 3
    ids = {c["place"]["id"] for c in candidates}
    assert not ids & {"126121", "130166"}
    assert all(c["detourMin"] == 20 for c in candidates)
    by_id = {c["place"]["id"]: c for c in candidates}
    # 시험용 혼잡 연결이 없는 장소는 정보 부족(crowd 없음)
    # 점수가 모두 같아 장소 ID 순: 범어사(126148)·해동용궁사(126848)·오륙도(1940208)
    assert set(by_id) == {"126148", "126848", "1940208"}
    assert by_id["126148"]["crowd"] is not None and by_id["126148"]["crowd"]["confidence"] == "낮음"
    assert by_id["126848"]["crowd"] is None and by_id["1940208"]["crowd"] is None


def _crowd(confidence: str) -> PlaceCrowdResponse:
    hours = [CrowdHour(h=h, grade="붐빔" if h == 14 else "여유", score=0.8 if h == 14 else 0.2) for h in range(24)]
    return PlaceCrowdResponse.model_validate(
        {"confidence": confidence, "asOf": "2026-10-01T00:00:00+09:00", "sources": ["s"], "hours": hours}
    )


def test_crowd_at_stay_uses_arrival_grade_and_penalizes_only_trusted_info() -> None:
    summary, penalty = crowd_at_stay(_crowd("중간"), time(14, 0), time(16, 0), "중간")
    assert summary is not None and summary.grade == "붐빔" and summary.confidence == "중간"
    assert penalty == pytest.approx(0.5)
    summary, penalty = crowd_at_stay(_crowd("낮음"), time(14, 0), time(15, 0), "중간")
    assert summary is not None and penalty is None
    assert crowd_at_stay(None, time(14), time(15), "중간") == (None, None)


def test_public_candidates_skip_places_without_stay() -> None:
    provider = PublicPlaceCandidates(lambda: ["b", "a", "c"], {"a": 30, "b": None, "c": 45}.get)
    rows = provider.candidates(on_date=datetime(2026, 12, 2).date())
    assert [row.ref.place_id for row in rows] == ["a", "c"]


def test_route_candidates_are_capped_by_straight_line_detour(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    class Counting(TwentyMinutes):
        def estimate(self, origin: object, destination: object, *, mode: str) -> RouteEstimate:
            calls.append(1)
            return super().estimate(origin, destination, mode=mode)

    monkeypatch.setattr("app.main.build_route_provider", Counting)
    monkeypatch.setattr("app.main.WAYPOINT_ROUTE_CANDIDATES", 2)
    with TestClient(create_app()) as client:
        trip_id = client.post("/api/trips", json=TRIP).json()["tripId"]
        client.post(f"/api/trips/{trip_id}/blocks", json=fixed("126121", "10:00", "11:00", 60))
        added = client.post(f"/api/trips/{trip_id}/blocks", json=fixed("130166", "15:00", "16:30", 90))
        first, second = (block["id"] for block in added.json()["schedule"]["days"][0]["blocks"])
        calls.clear()
        response = client.post(
            f"/api/trips/{trip_id}/waypoints/suggest",
            json={"fromBlockId": first, "toBlockId": second, "thresholdMin": 30},
        )
    assert response.status_code == 200
    assert len(response.json()["candidates"]) <= 2
    assert len(calls) <= 1 + 2 * 2 + 2  # 기준 1 + 후보 2곳 × 2 (+ 엔진 재계산 여유)


def test_schedule_days_carry_block_crowd_at_arrival(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """타임라인 배지(days[].crowd): 혼잡 근거가 있는 공공 장소 블록만, 도착 시각의 등급을 낸다."""
    monkeypatch.setattr("app.main.build_route_provider", TwentyMinutes)
    monkeypatch.setenv("CROWD_DATA_DIR", str(FIXTURES))
    with TestClient(create_app()) as client:
        trip_id = client.post("/api/trips", json=TRIP).json()["tripId"]
        client.post(f"/api/trips/{trip_id}/blocks", json=fixed("126121", "10:00", "11:00", 60))
        # 시험용 혼잡 연결이 있는 태종대(126658)
        added = client.post(f"/api/trips/{trip_id}/blocks", json=fixed("126658", "14:00", "15:30", 90))
    assert added.status_code == 200, added.text
    day = added.json()["schedule"]["days"][0]
    blocks = {block["place"]["id"]: block["id"] for block in day["blocks"]}
    crowd = {row["blockId"]: row for row in day["crowd"]}
    assert blocks["126121"] not in crowd  # 연결 없음 → 정보 부족
    row = crowd[blocks["126658"]]
    assert row["confidence"] in {"높음", "중간", "낮음"} and row["sources"]
