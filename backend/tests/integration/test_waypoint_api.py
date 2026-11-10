from datetime import UTC, date, datetime, time
from typing import Literal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import create_app
from app.modules.engine.interfaces import RouteEstimate
from app.modules.engine.schemas import (
    KakaoPlaceRef,
    OpeningHours,
    PublicPlaceRef,
    ScheduleState,
    TransientPlaceDetails,
)
from app.modules.engine.service import BasicItineraryEngine
from app.modules.recommend.waypoints import CandidateData, ScoreWeights, WaypointRecommender
from app.modules.trips.repository import FakeTripRepository, TripRecord
from app.modules.trips.schemas import CrowdSummary
from app.modules.trips.service import TripService
from tests.unit.engine.test_service import FakePlaces, _block, _details, _trip


class FakeCandidates:
    def __init__(self, values: tuple[CandidateData, ...]) -> None:
        self.values = values
        self.calls: list[date] = []

    def candidates(self, *, on_date: date) -> tuple[CandidateData, ...]:
        self.calls.append(on_date)
        return self.values


class MappedRoutes:
    """Deterministic route fake that records only opaque IDs, never coordinates."""

    def __init__(self, durations: dict[tuple[str, str], int | None]) -> None:
        self.durations = durations
        self.calls: list[tuple[str, str]] = []

    def estimate(
        self,
        origin: TransientPlaceDetails,
        destination: TransientPlaceDetails,
        *,
        mode: Literal["TRANSIT", "CAR", "WALK"],
    ) -> RouteEstimate:
        del mode
        pair = (_ref_id(origin), _ref_id(destination))
        self.calls.append(pair)
        return RouteEstimate(
            duration_min=self.durations.get(pair),
            source="ESTIMATED",
            computed_at=datetime(2026, 11, 2, tzinfo=UTC),
        )


def _ref_id(details: TransientPlaceDetails) -> str:
    ref = details.place_ref
    return ref.place_id if isinstance(ref, PublicPlaceRef) else ref.kakao_place_id


def _candidate(
    place_id: str,
    *,
    stay: int | None = 30,
    preference: float = 0,
    representative: float = 0,
) -> CandidateData:
    return CandidateData(
        ref=PublicPlaceRef(place_id=place_id),
        stay_min=stay,
        preference_match=preference,
        representativeness=representative,
    )


def _request(**overrides: object) -> dict[str, object]:
    return {"fromBlockId": "a", "toBlockId": "b", "thresholdMin": 15, **overrides}


def _setup(
    candidates: tuple[CandidateData, ...],
    durations: dict[tuple[str, str], int | None],
    *,
    state: ScheduleState | None = None,
    details: dict[str, TransientPlaceDetails] | None = None,
    weights: ScoreWeights | None = None,
) -> tuple[TestClient, FakeTripRepository, FakeCandidates, FakePlaces, MappedRoutes]:
    ids = {"a", "b", *(candidate.ref.place_id for candidate in candidates)}
    place_details = {
        place_id: _details(place_id, hours=OpeningHours(open_time=time(8), close_time=time(20))) for place_id in ids
    }
    place_details.update(details or {})
    places = FakePlaces(place_details)
    routes = MappedRoutes(durations)
    provider = FakeCandidates(candidates)
    schedule = state or ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 20, arrive=time(11), depart=time(11, 30), fixed=True),
        )
    )
    repository = FakeTripRepository({"trip": TripRecord(_trip(), schedule)})
    recommender = WaypointRecommender(
        provider,
        places,
        routes,
        weights
        or ScoreWeights(
            preference=1,
            representativeness=1,
            detour=1,
            crowd=1,
            missing_crowd_penalty=0,
        ),
    )
    service = TripService(
        repository,
        BasicItineraryEngine(places, routes),
        lambda place: None,
        recommender=recommender,
    )
    return TestClient(create_app(trip_service=service)), repository, provider, places, routes


@pytest.mark.parametrize(
    ("threshold", "detour", "expected"),
    [(10, 10, True), (10, 11, False), (15, 15, True), (15, 16, False), (30, 30, True), (30, 31, False)],
)
def test_detour_threshold_boundaries(threshold: int, detour: int, expected: bool) -> None:
    client, repository, _, _, _ = _setup(
        (_candidate("x"),),
        {("a", "b"): 20, ("a", "x"): 10, ("x", "b"): 10 + detour},
    )
    before = repository.get("trip")

    response = client.post("/api/trips/trip/waypoints/suggest", json=_request(thresholdMin=threshold))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert [candidate["detourMin"] for candidate in response.json()["candidates"]] == ([detour] if expected else [])
    assert repository.get("trip") == before


def test_empty_candidates_returns_200() -> None:
    client, repository, provider, _, routes = _setup((), {("a", "b"): 20})
    before = repository.get("trip")

    response = client.post("/api/trips/trip/waypoints/suggest", json=_request())

    assert response.status_code == 200
    assert response.json() == {"candidates": []}
    assert provider.calls == [date(2026, 11, 2)]
    assert routes.calls == [("a", "b")]
    assert repository.get("trip") == before


def test_scoring_is_deterministic_and_returns_at_most_three() -> None:
    candidates = tuple(
        _candidate(place_id, preference=preference, representative=representative)
        for place_id, preference, representative in (
            ("e", 0, 4),
            ("d", 1, 1),
            ("c", 2, 0),
            ("b2", 1, 5),
            ("a2", 1, 5),
        )
    )
    durations = {("a", "b"): 20}
    for candidate in candidates:
        durations[("a", candidate.ref.place_id)] = 10
        durations[(candidate.ref.place_id, "b")] = 10
    weights = ScoreWeights(
        preference=10,
        representativeness=1,
        detour=1,
        crowd=1,
        missing_crowd_penalty=0,
    )

    client, repository, _, _, _ = _setup(tuple(reversed(candidates)), durations, weights=weights)
    first = client.post("/api/trips/trip/waypoints/suggest", json=_request()).json()
    second = client.post("/api/trips/trip/waypoints/suggest", json=_request()).json()

    assert [candidate["place"]["id"] for candidate in first["candidates"]] == ["c", "a2", "b2"]
    assert first == second
    assert all(candidate["crowd"] is None for candidate in first["candidates"])
    assert all("우회 0분" in candidate["reason"] for candidate in first["candidates"])
    assert repository.get("trip") is not None


@pytest.mark.parametrize(
    ("candidate", "candidate_details", "route_overrides"),
    [
        (_candidate("x", stay=None), _details("x", hours=OpeningHours(open_time=time(8), close_time=time(20))), {}),
        (_candidate("x"), _details("x", hours=None), {}),
        (_candidate("x"), _details("x", hours=OpeningHours(is_closed=True)), {}),
        (
            _candidate("x"),
            _details(
                "x",
                hours=OpeningHours(
                    open_time=time(8), close_time=time(20), break_start=time(9, 35), break_end=time(10, 30)
                ),
            ),
            {},
        ),
        (_candidate("x"), _details("x", hours=OpeningHours(open_time=time(12), close_time=time(20))), {}),
        (
            _candidate("x"),
            _details("x", hours=OpeningHours(open_time=time(8), close_time=time(20)), lat=None),
            {},
        ),
        (
            _candidate("x"),
            _details("x", hours=OpeningHours(open_time=time(8), close_time=time(20))),
            {("a", "x"): None},
        ),
    ],
)
def test_unverifiable_or_constrained_candidate_is_excluded(
    candidate: CandidateData,
    candidate_details: TransientPlaceDetails,
    route_overrides: dict[tuple[str, str], int | None],
) -> None:
    durations: dict[tuple[str, str], int | None] = {
        ("a", "b"): 20,
        ("a", "x"): 10,
        ("x", "b"): 10,
        **route_overrides,
    }
    client, _, _, _, _ = _setup((candidate,), durations, details={"x": candidate_details})

    response = client.post("/api/trips/trip/waypoints/suggest", json=_request())

    assert response.status_code == 200
    assert response.json() == {"candidates": []}


def test_fixed_time_conflict_excludes_candidate_and_keeps_state() -> None:
    state = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 20, arrive=time(10), depart=time(10, 30), fixed=True),
            _block("c", 30, arrive=time(11), depart=time(11, 30), fixed=True),
        )
    )
    client, repository, _, _, routes = _setup(
        (_candidate("x", stay=30),),
        {("a", "b"): 15, ("a", "x"): 15, ("x", "b"): 20, ("b", "c"): 15},
        state=state,
        details={"c": _details("c", hours=OpeningHours(open_time=time(8), close_time=time(20)))},
    )
    before = repository.get("trip")

    response = client.post("/api/trips/trip/waypoints/suggest", json=_request(thresholdMin=30))

    assert response.status_code == 200
    assert response.json() == {"candidates": []}
    assert ("b", "c") in routes.calls
    assert repository.get("trip") == before


@pytest.mark.parametrize(
    "body",
    [
        _request(fromBlockId="b", toBlockId="a"),
        _request(fromBlockId="missing"),
        _request(fromBlockId="a", toBlockId="a"),
    ],
)
def test_non_adjacent_or_missing_blocks_return_err001(body: dict[str, object]) -> None:
    client, repository, _, _, routes = _setup((_candidate("x"),), {("a", "b"): 20})
    before = repository.get("trip")

    response = client.post("/api/trips/trip/waypoints/suggest", json=body)

    assert response.status_code == 400
    assert response.json()["error"]["id"] == "ERR-001"
    assert routes.calls == []
    assert repository.get("trip") == before


def test_cross_day_blocks_are_rejected() -> None:
    state = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 10, arrive=time(11), depart=time(11, 30), fixed=True, day_no=2),
        )
    )
    client, repository, _, _, _ = _setup((_candidate("x"),), {}, state=state)
    before = repository.get("trip")

    response = client.post("/api/trips/trip/waypoints/suggest", json=_request())

    assert response.status_code == 400
    assert response.json()["error"]["id"] == "ERR-001"
    assert repository.get("trip") == before


@pytest.mark.parametrize("threshold", [9, 11, 20, 31, "15"])
def test_invalid_threshold_returns_sanitized_err001(threshold: object) -> None:
    client, repository, _, _, routes = _setup((_candidate("x"),), {("a", "b"): 20})
    before = repository.get("trip")

    response = client.post("/api/trips/trip/waypoints/suggest", json=_request(thresholdMin=threshold))

    assert response.status_code == 400
    assert response.json() == {"error": {"id": "ERR-001", "message": "입력 형식이 올바르지 않습니다."}}
    assert routes.calls == []
    assert repository.get("trip") == before


def test_kakao_coordinates_are_request_scoped_not_logged_or_stored(caplog: pytest.LogCaptureFixture) -> None:
    kakao = KakaoPlaceRef(
        kakao_place_id="123",
        kakao_place_url="https://place.map.kakao.com/123",
    )
    state = ScheduleState(
        blocks=(
            _block("a", 10, ref=kakao, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 20, arrive=time(11), depart=time(11, 30), fixed=True),
        )
    )
    client, repository, _, _, routes = _setup(
        (_candidate("x"),),
        {("123", "b"): 20, ("123", "x"): 10, ("x", "b"): 10},
        state=state,
    )
    before = repository.get("trip")
    body = _request(sessionCoords={"123": {"lat": 35.1234567, "lng": 129.7654321}})

    first = client.post("/api/trips/trip/waypoints/suggest", json=body)
    calls = len(routes.calls)
    second = client.post("/api/trips/trip/waypoints/suggest", json=_request())

    assert first.status_code == 200
    assert len(first.json()["candidates"]) == 1
    assert second.status_code == 200
    assert second.json() == {"candidates": []}
    assert len(routes.calls) == calls
    combined = first.text + second.text + caplog.text + repr(repository.get("trip")) + before.schedule.model_dump_json()
    for secret in ("35.1234567", "129.7654321", "sessionCoords"):
        assert secret not in combined
    assert repository.get("trip") == before


def test_provider_exception_is_sanitized_and_does_not_save(caplog: pytest.LogCaptureFixture) -> None:
    client, repository, provider, _, _ = _setup((_candidate("x"),), {("a", "b"): 20})
    before = repository.get("trip")
    secret = "synthetic-kakao-name-35.1234567"

    def fail(*, on_date: date) -> tuple[CandidateData, ...]:
        del on_date
        raise RuntimeError(secret)

    provider.candidates = fail  # type: ignore[method-assign]
    response = client.post("/api/trips/trip/waypoints/suggest", json=_request())

    assert response.status_code == 503
    assert response.json()["error"]["id"] == "ERR-017"
    assert secret not in response.text + caplog.text
    assert repository.get("trip") == before


def test_missing_baseline_route_returns_empty_without_querying_candidates() -> None:
    client, repository, provider, _, routes = _setup((_candidate("x"),), {("a", "b"): None})
    before = repository.get("trip")

    response = client.post("/api/trips/trip/waypoints/suggest", json=_request())

    assert response.status_code == 200
    assert response.json() == {"candidates": []}
    assert provider.calls == []
    assert routes.calls == [("a", "b")]
    assert repository.get("trip") == before


def test_duplicate_candidate_ids_are_excluded_as_ambiguous() -> None:
    duplicate = _candidate("x")
    client, _, _, _, _ = _setup(
        (duplicate, duplicate),
        {("a", "b"): 20, ("a", "x"): 10, ("x", "b"): 10},
    )

    response = client.post("/api/trips/trip/waypoints/suggest", json=_request())

    assert response.status_code == 200
    assert response.json() == {"candidates": []}


def test_stale_fixed_anchor_is_not_used_to_recommend_an_impossible_visit() -> None:
    first = _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True)
    first = first.model_copy(update={"arrive_at": time(8, 30), "depart_at": time(9)})
    state = ScheduleState(
        blocks=(
            first,
            _block("b", 20, arrive=time(10), depart=time(10, 30), fixed=True),
        )
    )
    client, repository, provider, _, routes = _setup(
        (_candidate("x"),),
        {("a", "b"): 15, ("a", "x"): 15, ("x", "b"): 15},
        state=state,
    )
    before = repository.get("trip")
    response = client.post("/api/trips/trip/waypoints/suggest", json=_request())
    assert response.status_code == 200
    assert response.json() == {"candidates": []}
    assert not routes.calls
    assert not provider.calls
    assert repository.get("trip") == before


def test_later_fixed_block_conflict_excludes_candidate() -> None:
    state = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 20, arrive=time(9, 45), depart=time(10, 15)),
            _block("c", 30, arrive=time(10, 30), depart=time(11), fixed=True),
        )
    )
    client, repository, _, _, _ = _setup(
        (_candidate("x"),),
        {("a", "b"): 15, ("a", "x"): 15, ("x", "b"): 15, ("b", "c"): 15},
        state=state,
        details={"c": _details("c", hours=OpeningHours(open_time=time(8), close_time=time(20)))},
    )
    before = repository.get("trip")
    response = client.post("/api/trips/trip/waypoints/suggest", json=_request())
    assert response.status_code == 200
    assert response.json() == {"candidates": []}
    assert repository.get("trip") == before


def test_crowd_penalty_and_configured_missing_penalty_affect_order():
    crowd = CrowdSummary(grade="붐빔", confidence="중간", as_of=datetime(2026, 11, 2, tzinfo=UTC))
    crowded = _candidate("crowded", preference=10).model_copy(update={"crowd": crowd, "crowd_penalty": 9})
    unknown = _candidate("unknown", preference=10)
    quiet = _candidate("quiet", preference=10).model_copy(update={"crowd": crowd, "crowd_penalty": 1})
    durations = {("a", "b"): 20}
    for name in ("crowded", "unknown", "quiet"):
        durations[("a", name)] = 10
        durations[(name, "b")] = 10
    client, _, provider, _, _ = _setup(
        (crowded, unknown, quiet),
        durations,
        weights=ScoreWeights(
            preference=1,
            representativeness=1,
            detour=1,
            crowd=2,
            missing_crowd_penalty=3,
        ),
    )
    first = client.post("/api/trips/trip/waypoints/suggest", json=_request())
    assert first.status_code == 200
    assert [c["place"]["id"] for c in first.json()["candidates"]] == ["quiet", "unknown", "crowded"]
    assert first.json()["candidates"][1]["crowd"] is None
    provider.values = tuple(reversed(provider.values))
    second = client.post("/api/trips/trip/waypoints/suggest", json=_request())
    assert first.json() == second.json()


def test_recommendation_never_calls_repository_save():
    client, repository, _, _, _ = _setup(
        (_candidate("x"),),
        {("a", "b"): 20, ("a", "x"): 10, ("x", "b"): 10},
    )

    def forbid_save(*args, **kwargs):
        pytest.fail("Recommendation must not save even an unchanged state")

    repository.save = forbid_save
    response = client.post("/api/trips/trip/waypoints/suggest", json=_request())
    assert response.status_code == 200
    assert len(response.json()["candidates"]) == 1


def test_invalid_kakao_data_does_not_escape_validation_errors(caplog):
    client, repository, _, _, routes = _setup((_candidate("x"),), {("a", "b"): 20})
    secret = "synthetic-kakao-name-35.1234567"
    before = repository.get("trip")
    response = client.post(
        "/api/trips/trip/waypoints/suggest",
        json=_request(
            sessionCoords={"123": {"lat": secret, "lng": 129.7654321, "name": secret}},
        ),
    )
    assert response.status_code == 400
    assert response.json()["error"]["id"] == "ERR-001"
    assert secret not in response.text + caplog.text
    assert "129.7654321" not in response.text + caplog.text
    assert not routes.calls
    assert repository.get("trip") == before


def test_candidate_model_rejects_kakao_sources():
    with pytest.raises(ValidationError):
        CandidateData.model_validate(
            {
                "ref": {"kind": "KAKAO", "kakaoPlaceId": "123", "placeUrl": "https://place.map.kakao.com/123"},
                "stayMin": 30,
                "preferenceMatch": 1,
                "representativeness": 1,
            }
        )


def test_existing_but_non_adjacent_blocks_are_rejected():
    state = ScheduleState(
        blocks=(
            _block("a", 1, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 2, arrive=time(10), depart=time(10, 30)),
            _block("c", 3, arrive=time(11), depart=time(11, 30), fixed=True),
        )
    )
    client, _, _, _, routes = _setup((_candidate("x"),), {}, state=state)
    response = client.post("/api/trips/trip/waypoints/suggest", json=_request(toBlockId="c"))
    assert response.status_code == 400
    assert response.json()["error"]["id"] == "ERR-001"
    assert not routes.calls


def test_detour_cost_reduces_score_without_adding_stay_to_detour():
    client, _, _, _, _ = _setup(
        (_candidate("short", stay=40), _candidate("long", stay=20)),
        {("a", "b"): 20, ("a", "short"): 10, ("short", "b"): 10, ("a", "long"): 15, ("long", "b"): 15},
    )
    response = client.post("/api/trips/trip/waypoints/suggest", json=_request())
    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert [c["place"]["id"] for c in candidates] == ["short", "long"]
    assert [c["detourMin"] for c in candidates] == [0, 10]
    assert [c["stayMin"] for c in candidates] == [40, 20]
