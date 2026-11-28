"""FR-010 플랜 B(API-014·015): 붐빌 때 강행 / 순서 바꾸기 / 대체 장소 3안, 고르기 전에는 일정 유지, 고정 블록 불변.

경로는 고정 20분 가짜, 혼잡은 시험용 가짜 조회(장소·시각별 등급)다.
"""

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import _stay, create_app
from app.modules.crowd.schemas import CrowdHour, PlaceCrowdResponse
from app.modules.engine.initial import InitialSchedulePlanner
from app.modules.engine.interfaces import RouteEstimate
from app.modules.engine.schemas import PlaceRef, PublicPlaceRef
from app.modules.engine.service import BasicItineraryEngine
from app.modules.places.samples import load_sample_places
from app.modules.plan_b.service import PlanBPlanner
from app.modules.recommend.waypoints import PublicPlaceCandidates
from app.modules.trips.initial import PublicStayDurations
from app.modules.trips.repository import FakeTripRepository
from app.modules.trips.service import TripService

YONGDUSAN, ART, TAEJONGDAE = "126121", "130166", "126658"
# 2026-12-02(수) 09:00–20:00. 미술관 10–11 고정, 용두산(시간 안 정함), 태종대 15–16 고정
TRIP = {
    "dates": {"start": "2026-12-02", "end": "2026-12-02"},
    "dayStart": "09:00",
    "dayEnd": "20:00",
    "mode": "TRANSIT",
}


class TwentyMinutes:
    def estimate(self, origin: object, destination: object, *, mode: str) -> RouteEstimate:
        return RouteEstimate(20, "ESTIMATED", datetime(2026, 12, 1, tzinfo=UTC))


def _crowd(busy_hours: set[int], confidence: str = "중간") -> PlaceCrowdResponse:
    hours = [
        CrowdHour(h=h, grade="붐빔" if h in busy_hours else "여유", score=0.9 if h in busy_hours else 0.1)
        for h in range(24)
    ]
    return PlaceCrowdResponse.model_validate(
        {"confidence": confidence, "asOf": "2026-10-01T00:00:00+09:00", "sources": ["시험용"], "hours": hours}
    )


class FakeCrowd:
    """용두산은 오전(11–13시)만 붐빈다. 다른 공공 장소는 하루 종일 여유(신뢰 중간)."""

    def __init__(self, yongdusan_confidence: str = "중간") -> None:
        self.yongdusan_confidence = yongdusan_confidence

    def crowd(self, place_ref: PlaceRef, *, on_date: date) -> PlaceCrowdResponse | None:
        if not isinstance(place_ref, PublicPlaceRef):
            return None
        if place_ref.place_id == YONGDUSAN:
            return _crowd({11, 12, 13}, self.yongdusan_confidence)
        return _crowd(set())


def _app(crowd: FakeCrowd) -> TestClient:
    places = load_sample_places()
    engine = BasicItineraryEngine(places, TwentyMinutes(), crowd=crowd)
    candidates = PublicPlaceCandidates(lambda: [item.place.id for item in places.all()], lambda pid: _stay(places, pid))
    service = TripService(
        FakeTripRepository({}),
        engine,
        places.stay_min,
        initial_planner=InitialSchedulePlanner(engine, PublicStayDurations(places.stay_min)),
        plan_b=PlanBPlanner(engine, places, candidates, crowd=crowd),
    )
    return TestClient(create_app(trip_service=service))


def _fixed(place_id: str, start: str, end: str) -> dict[str, object]:
    window = {"dayNo": 1, "start": start, "end": end}
    return {"clientId": place_id, "place": {"placeId": place_id}, "dayNo": 1, "fixedWindow": window}


def _trip(client: TestClient) -> tuple[str, dict[str, dict[str, object]]]:
    trip_id = client.post("/api/trips", json=TRIP).json()["tripId"]
    selections = [
        _fixed(ART, "10:00", "11:00"),
        {"clientId": YONGDUSAN, "place": {"placeId": YONGDUSAN}, "stayMin": 45},
        _fixed(TAEJONGDAE, "15:00", "16:00"),
    ]
    response = client.post(
        f"/api/trips/{trip_id}/schedule", json={"initial": {"policy": "FIRST_FEASIBLE", "selections": selections}}
    )
    assert response.status_code == 200, response.text
    blocks = {block["place"]["id"]: block for block in response.json()["days"][0]["blocks"]}
    # 혼잡 회피 없이 첫 자리: 미술관 뒤 11시대(붐빔)
    assert blocks[YONGDUSAN]["arriveAt"] == "11:20"
    return trip_id, blocks


def _fixed_times(schedule: dict[str, object]) -> dict[str, tuple[str, str]]:
    days = schedule["days"]
    assert isinstance(days, list)
    return {b["place"]["id"]: (b["arriveAt"], b["departAt"]) for day in days for b in day["blocks"] if b["isFixed"]}


def test_crowded_flexible_block_gets_three_options_without_changing_schedule() -> None:
    with _app(FakeCrowd()) as client:
        trip_id, blocks = _trip(client)
        before = client.get(f"/api/trips/{trip_id}").json()
        response = client.get(f"/api/trips/{trip_id}/plan-b", params={"blockId": blocks[YONGDUSAN]["id"]})
        after = client.get(f"/api/trips/{trip_id}").json()
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["trigger"] == "CROWD"
    assert body["crowd"]["grade"] == "붐빔" and body["crowd"]["confidence"] == "중간"
    keep, reorder, replace = body["options"]
    assert (keep["kind"], keep["available"], keep["extraMinutes"]) == ("KEEP", True, 0)
    # 순서 바꾸기: 태종대 뒤(16:20)로 옮기면 여유. 고정 시각은 그대로 지킨다.
    assert reorder["kind"] == "REORDER" and reorder["available"]
    assert reorder["arriveAt"] == "16:20" and reorder["crowd"]["grade"] == "여유"
    assert reorder["extraMinutes"] == 0
    # 대체 장소: 일정에 없는 공공 장소, 그 시각 여유
    assert replace["kind"] == "REPLACE" and replace["available"]
    assert replace["place"]["id"] not in {YONGDUSAN, ART, TAEJONGDAE}
    assert replace["crowd"]["grade"] == "여유"
    # 조회는 저장하지 않는다(원칙 5).
    assert before == after


def test_fixed_or_low_confidence_blocks_do_not_trigger() -> None:
    with _app(FakeCrowd()) as client:
        trip_id, blocks = _trip(client)
        fixed = client.get(f"/api/trips/{trip_id}/plan-b", params={"blockId": blocks[ART]["id"]}).json()
    assert fixed["trigger"] is None and fixed["options"] == []
    with _app(FakeCrowd(yongdusan_confidence="낮음")) as client:
        trip_id, blocks = _trip(client)
        low = client.get(f"/api/trips/{trip_id}/plan-b", params={"blockId": blocks[YONGDUSAN]["id"]}).json()
    # 신뢰도 낮음: 등급은 보여 주되 플랜 B 를 띄우지 않는다.
    assert low["trigger"] is None and low["crowd"]["grade"] == "붐빔"


@pytest.mark.parametrize("kind", ["REORDER", "REPLACE"])
def test_apply_keeps_fixed_times_and_can_be_undone(kind: str) -> None:
    with _app(FakeCrowd()) as client:
        trip_id, blocks = _trip(client)
        before = client.get(f"/api/trips/{trip_id}").json()
        options = client.get(f"/api/trips/{trip_id}/plan-b", params={"blockId": blocks[YONGDUSAN]["id"]}).json()
        option = next(o for o in options["options"] if o["kind"] == kind)
        applied = client.post(f"/api/trips/{trip_id}/plan-b/apply", json={"optionId": option["id"]})
        assert applied.status_code == 200, applied.text
        schedule = applied.json()["schedule"]
        detail = client.get(f"/api/trips/{trip_id}").json()
        undone = client.post(f"/api/trips/{trip_id}/undo")
        restored = client.get(f"/api/trips/{trip_id}").json()
    assert _fixed_times(schedule) == _fixed_times(before["schedule"])
    placed = {b["place"]["id"]: b for b in schedule["days"][0]["blocks"]}
    if kind == "REORDER":
        assert [b["place"]["id"] for b in schedule["days"][0]["blocks"]] == [ART, TAEJONGDAE, YONGDUSAN]
        assert placed[YONGDUSAN]["arriveAt"] == "16:20"
    else:
        assert YONGDUSAN not in placed and option["place"]["id"] in placed
        assert placed[option["place"]["id"]]["origin"] == "SUGGESTED"
    assert detail["canUndo"] is True
    assert undone.status_code == 200
    assert restored["schedule"] == before["schedule"]


def test_keep_changes_nothing_and_unknown_options_are_rejected() -> None:
    with _app(FakeCrowd()) as client:
        trip_id, blocks = _trip(client)
        before = client.get(f"/api/trips/{trip_id}").json()
        keep = client.post(f"/api/trips/{trip_id}/plan-b/apply", json={"optionId": "KEEP"})
        after = client.get(f"/api/trips/{trip_id}").json()
        bad = [
            client.post(f"/api/trips/{trip_id}/plan-b/apply", json={"optionId": option_id})
            for option_id in (
                "NOPE",
                f"REORDER:{blocks[YONGDUSAN]['id']}:x",
                f"REORDER:{blocks[ART]['id']}:2",  # 고정 블록
                f"REPLACE:{blocks[YONGDUSAN]['id']}:{TAEJONGDAE}",  # 이미 일정에 있는 장소
            )
        ]
        missing = client.get(f"/api/trips/{trip_id}/plan-b", params={"blockId": "missing"})
    assert keep.status_code == 200
    assert after == before and after["canUndo"] is False
    assert [response.status_code for response in bad] == [400, 400, 400, 400]
    assert missing.status_code == 400
