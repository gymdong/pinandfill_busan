"""Synthetic, network-free initial scheduling acceptance cases."""

from datetime import UTC, date, datetime, time

import pytest
from pydantic import ValidationError

import app.modules.engine.initial as initial
from app.modules.crowd.avoidance import AvoidanceSettings
from app.modules.crowd.engine_lookup import CrowdServiceLookup
from app.modules.crowd.schemas import CrowdHour, PlaceCrowdResponse
from app.modules.crowd.service import CrowdService
from app.modules.engine.initial import (
    MAX_ROUTE_LOOKUPS_PER_PLAN,
    InitialScheduleCommand,
    InitialSchedulePlanner,
    InitialScheduleResult,
    InitialSelection,
    UnplacedSelection,
)
from app.modules.engine.interfaces import RouteEstimate
from app.modules.engine.schemas import (
    CalculationContext,
    FixedWindow,
    KakaoPlaceRef,
    OpeningHours,
    PublicPlaceRef,
    ScheduleConflict,
    ScheduleState,
    SessionCoordinate,
    StoredBlock,
    TransientPlaceDetails,
    TripWindow,
    Violation,
)
from app.modules.engine.service import BasicItineraryEngine, NeedsConfirmationError
from app.modules.trips.schemas import MAX_INITIAL_SELECTIONS, Schedule


class Places:
    def __init__(self):
        self.hours = {}
        self.missing_coords = set()
        self.incomplete = set()

    def get(self, ref, *, on_date):
        assert isinstance(ref, PublicPlaceRef)
        key = ref.place_id
        return TransientPlaceDetails(
            place_ref=ref,
            name=None if key in self.incomplete else "Synthetic public place",
            lat=None if key in self.missing_coords else 35.123,
            lng=None if key in self.missing_coords else 129.123,
            category="TEST",
            ref_date=date(2026, 11, 1),
            hours=self.hours.get((key, on_date), OpeningHours(open_time=time(8), close_time=time(23, 59))),
        )


class Routes:
    def __init__(self):
        self.duration = 15
        self.source = "TMAP"
        self.semantics = "prediction"
        self.departures = []

    def estimate(self, origin, destination, *, mode):
        raise AssertionError("departure-aware method required")

    def estimate_at(self, origin, destination, *, mode, departure_at):
        assert origin.lat is not None and destination.lat is not None
        self.departures.append(departure_at)
        return RouteEstimate(self.duration, self.source, datetime(2026, 11, 1, tzinfo=UTC), self.semantics)


class Stays:
    def __init__(self, value=30):
        self.value = value
        self.calls = 0

    def get(self, place_ref, *, on_date):
        self.calls += 1
        return self.value


def selection(key, **kwargs):
    return InitialSelection(block_id=key, place_ref=PublicPlaceRef(place_id=key), **kwargs)


def command(*selections, days=1, start=time(9), end=time(18)):
    return InitialScheduleCommand(
        trip=TripWindow(
            start_date=date(2026, 11, 14),
            end_date=date(2026, 11, 13 + days),
            day_start=start,
            day_end=end,
            transport_mode="CAR",
        ),
        selections=selections,
        policy="FIRST_FEASIBLE",
    )


def setup(stay=30, tag=None):
    places, routes, stays = Places(), Routes(), Stays(stay)
    engine = BasicItineraryEngine(places, routes)
    return InitialSchedulePlanner(engine, stays, tag_stays=tag), places, routes, stays


def test_initial_generation_and_wire_shape_are_reproducible():
    planner, _, routes, _ = setup()
    request = command(selection("a"), selection("b"), selection("c"))
    first = planner.plan(request)
    second = planner.plan(request)
    assert first == second
    assert first.confirmed and not first.unplaced
    assert len(first.state.blocks) == 3
    assert [b.seq for b in first.state.blocks] == [1, 2, 3]
    assert first.schedule is not None
    payload = first.schedule.model_dump(mode="json", by_alias=True)
    assert set(payload) == {"days", "violations", "conflicts"}
    assert Schedule.model_validate(payload) == first.schedule
    assert routes.departures and all(d.utcoffset().total_seconds() == 32400 for d in routes.departures)


def test_multiple_days_and_allowed_days():
    planner, _, _, _ = setup(stay=60)
    result = planner.plan(
        command(selection("a", allowed_days=(1,)), selection("b", allowed_days=(2,)), days=2, end=time(10))
    )
    assert result.confirmed
    assert [(b.id, b.day_no) for b in result.state.blocks] == [("a", 1), ("b", 2)]


def test_overfull_day_spills_to_next_day():
    planner, _, _, _ = setup(stay=60)
    result = planner.plan(command(selection("a"), selection("b"), days=2, end=time(10)))
    assert {b.day_no for b in result.state.blocks} == {1, 2}
    assert not result.unplaced


def test_fixed_windows_and_relative_order_are_preserved():
    planner, _, _, _ = setup()
    request = command(
        selection("pin1", fixed_window=FixedWindow(day_no=1, start=time(11), end=time(11, 30))),
        selection("pin2", fixed_window=FixedWindow(day_no=1, start=time(15), end=time(15, 30))),
        selection("free"),
    )
    result = planner.plan(request)
    pins = [b for b in result.state.blocks if b.is_fixed]
    assert [(b.id, b.arrive_at, b.depart_at) for b in pins] == [
        ("pin1", time(11), time(11, 30)),
        ("pin2", time(15), time(15, 30)),
    ]
    assert result.confirmed


def test_contradictory_fixed_order_reports_conflict_not_reordering():
    planner, _, _, _ = setup()
    result = planner.plan(
        command(
            selection("late", fixed_window=FixedWindow(day_no=1, start=time(15), end=time(15, 30))),
            selection("early", fixed_window=FixedWindow(day_no=1, start=time(11), end=time(11, 30))),
        )
    )
    assert not result.confirmed and result.conflicts
    assert [b.id for b in result.state.blocks] == ["late", "early"]
    assert result.state.blocks[0].arrive_at == time(15)


def test_fixed_travel_conflict_preserves_pins():
    planner, _, routes, _ = setup()
    routes.duration = 60
    result = planner.plan(
        command(
            selection("a", fixed_window=FixedWindow(day_no=1, start=time(10), end=time(10, 30))),
            selection("b", fixed_window=FixedWindow(day_no=1, start=time(11), end=time(11, 30))),
        )
    )
    assert not result.confirmed and result.conflicts
    assert result.state.blocks[1].arrive_at == time(11)


@pytest.mark.parametrize(
    "hours", [None, OpeningHours(is_closed=True), OpeningHours(open_time=time(17, 45), close_time=time(18))]
)
def test_missing_hours_closed_or_insufficient_hours_not_confirmed(hours):
    planner, places, _, _ = setup()
    places.hours[("a", date(2026, 11, 14))] = hours
    result = planner.plan(command(selection("a")))
    assert not result.confirmed
    assert result.unplaced or result.violations


def test_waits_for_opening_and_break_end():
    planner, places, _, _ = setup()
    places.hours[("a", date(2026, 11, 14))] = OpeningHours(
        open_time=time(10), close_time=time(18), break_start=time(10), break_end=time(11)
    )
    result = planner.plan(command(selection("a")))
    assert result.state.blocks[0].arrive_at == time(11)
    assert result.confirmed


def test_closed_first_day_can_use_second():
    planner, places, _, _ = setup()
    places.hours[("a", date(2026, 11, 14))] = OpeningHours(is_closed=True)
    result = planner.plan(command(selection("a"), days=2))
    assert result.state.blocks[0].day_no == 2
    assert result.confirmed


def test_user_stay_wins_over_db():
    planner, _, _, stays = setup(stay=90)
    result = planner.plan(command(selection("a", stay_min=20)))
    assert result.state.blocks[0].stay_min == 20
    assert stays.calls == 0


def test_missing_stay_is_unplaced_without_fake_default():
    planner, _, _, _ = setup(stay=None)
    result = planner.plan(command(selection("a")))
    assert not result.confirmed and not result.state.blocks
    assert result.unplaced[0].block_id == "a"


def test_explicit_tag_fallback_only():
    planner, _, _, _ = setup(stay=None, tag=Stays(45))
    result = planner.plan(command(selection("a")))
    assert result.state.blocks[0].stay_min == 45


@pytest.mark.parametrize("duration", [None, 180])
def test_unavailable_or_too_long_route_never_confirms_all(duration):
    planner, _, routes, _ = setup()
    routes.duration = duration
    result = planner.plan(command(selection("a"), selection("b"), end=time(10)))
    assert not result.confirmed and result.unplaced
    assert len(result.state.blocks) < 2


def test_first_missing_coords_never_confirmed():
    planner, places, routes, _ = setup()
    places.missing_coords.add("a")
    result = planner.plan(command(selection("a")))
    assert not result.confirmed
    assert not routes.departures


@pytest.mark.parametrize("stay", [60, 90])
def test_midnight_never_wraps_or_fabricates_next_day(stay):
    planner, _, _, _ = setup(stay=stay)
    result = planner.plan(command(selection("a"), start=time(23), end=time(23, 59)))
    assert not result.confirmed and result.unplaced
    assert not result.state.blocks


@pytest.mark.parametrize(
    ("source", "semantics"),
    [("ESTIMATED", "unspecified"), ("TMAP", "service_availability"), ("ODSAY", "search_context")],
)
def test_estimate_or_context_only_is_not_exact(source, semantics):
    planner, _, routes, _ = setup()
    routes.source, routes.semantics = source, semantics
    result = planner.plan(command(selection("a"), selection("b")))
    assert not result.confirmed


def test_kakao_context_not_serialized_or_retained(caplog):
    planner, _, _, _ = setup()
    ref = KakaoPlaceRef(kakao_place_id="123", kakao_place_url="https://place.map.kakao.com/123")
    request = command(
        InitialSelection(
            block_id="k",
            place_ref=ref,
            stay_min=30,
            fixed_window=FixedWindow(day_no=1, start=time(10), end=time(10, 30)),
        )
    )
    context = CalculationContext(session_coords={"123": SessionCoordinate(lat=35.987654, lng=129.876543)})
    result = planner.plan(request, context=context)
    text = result.state.model_dump_json() + repr(result) + caplog.text
    assert "35.987654" not in text and "129.876543" not in text
    assert "123" in result.state.model_dump_json()
    assert not result.confirmed  # no authoritative Kakao opening hours
    again = planner.plan(request)
    assert any(v.type == "COORDS_NEEDS_CHECK" for v in again.violations)


def test_explicit_policy_required():
    with pytest.raises(ValidationError):
        InitialScheduleCommand(trip=command().trip, selections=())


def test_route_exception_is_sanitized(caplog, monkeypatch):
    planner, _, routes, _ = setup()

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic-secret-token 35.987654 129.876543")

    monkeypatch.setattr(routes, "estimate_at", fail)
    result = planner.plan(command(selection("a"), selection("b")))
    assert not result.confirmed
    assert result.unplaced
    safe = repr(result) + caplog.text
    assert "synthetic-secret-token" not in safe
    assert "35.987654" not in safe


def test_incomplete_public_display_does_not_fabricate_name():
    planner, places, _, _ = setup()
    places.incomplete.add("a")
    result = planner.plan(command(selection("a")))
    assert not result.confirmed
    assert result.schedule is None or result.unplaced


def test_duplicate_ids_are_rejected():
    with pytest.raises((ValidationError, ValueError)):
        planner, _, _, _ = setup()
        planner.plan(command(selection("same"), selection("same")))


@pytest.mark.parametrize("hours", [OpeningHours(is_closed=True), OpeningHours(open_time=time(12), close_time=time(18))])
def test_fixed_hours_violation_never_confirmed(hours):
    planner, places, _, _ = setup()
    places.hours[("a", date(2026, 11, 14))] = hours
    result = planner.plan(command(selection("a", fixed_window=FixedWindow(day_no=1, start=time(10), end=time(10, 30)))))
    assert result.state.blocks[0].arrive_at == time(10)
    assert result.violations
    assert not result.confirmed


@pytest.mark.parametrize("fail_after", range(1, 7))
def test_provider_changes_do_not_silently_drop_accepted_selections(monkeypatch, fail_after):
    planner, _, routes, _ = setup()
    original = routes.estimate_at
    calls = 0

    def changing(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > fail_after:
            raise RuntimeError("synthetic provider unavailable")
        return original(*args, **kwargs)

    monkeypatch.setattr(routes, "estimate_at", changing)
    result = planner.plan(command(selection("a"), selection("b"), selection("c")))
    selected = {b.id for b in result.state.blocks}
    unresolved = {u.block_id for u in result.unplaced}
    assert selected.isdisjoint(unresolved)
    assert selected | unresolved == {"a", "b", "c"}


def test_kakao_stay_never_reaches_public_duration_provider():
    planner, _, _, stays = setup()
    ref = KakaoPlaceRef(kakao_place_id="123", kakao_place_url="https://place.map.kakao.com/123")
    result = planner.plan(command(InitialSelection(block_id="k", place_ref=ref)))
    assert stays.calls == 0
    assert result.unplaced[0].block_id == "k"


def test_contradictory_fixed_days_do_not_claim_preserved_order():
    planner, _, _, _ = setup()
    result = planner.plan(
        command(
            selection("second", fixed_window=FixedWindow(day_no=2, start=time(10), end=time(10, 30))),
            selection("first", fixed_window=FixedWindow(day_no=1, start=time(10), end=time(10, 30))),
            days=2,
        )
    )
    assert not result.confirmed
    assert result.conflicts


@pytest.mark.parametrize("duration", [-1, True])
def test_invalid_route_duration_is_not_used(duration):
    planner, _, routes, _ = setup()
    routes.duration = duration
    result = planner.plan(command(selection("a"), selection("b")))
    assert not result.confirmed
    assert result.unplaced


def test_unknown_route_source_cannot_confirm_a_duration():
    planner, _, routes, _ = setup()
    routes.source = "UNKNOWN"
    result = planner.plan(command(selection("a"), selection("b")))
    assert not result.confirmed


def test_unknown_route_before_pin_skips_overlap_and_tries_valid_later_gap(monkeypatch):
    planner, _, routes, _ = setup()

    def estimate(origin, destination, *, mode, departure_at):
        pair = (origin.place_ref.place_id, destination.place_ref.place_id)
        source = "UNKNOWN" if pair == ("b", "a") else "TMAP"
        return RouteEstimate(15, source, datetime(2026, 11, 1, tzinfo=UTC), "prediction")

    monkeypatch.setattr(routes, "estimate_at", estimate)
    result = planner.plan(
        command(
            selection("a", fixed_window=FixedWindow(day_no=1, start=time(9), end=time(9, 30))),
            selection("b", stay_min=30),
        )
    )

    assert not result.unplaced
    assert [(block.id, block.arrive_at, block.depart_at) for block in result.state.blocks] == [
        ("a", time(9), time(9, 30)),
        ("b", time(9, 45), time(10, 15)),
    ]
    assert result.confirmed


def test_unknown_routes_before_and_after_pin_continue_to_next_day():
    planner, _, routes, _ = setup()
    routes.source = "UNKNOWN"
    result = planner.plan(
        command(
            selection("a", fixed_window=FixedWindow(day_no=1, start=time(9), end=time(9, 30))),
            selection("b", stay_min=30),
            days=2,
        )
    )

    assert not result.unplaced
    assert [(block.id, block.day_no, block.arrive_at, block.depart_at) for block in result.state.blocks] == [
        ("a", 1, time(9), time(9, 30)),
        ("b", 2, time(9), time(9, 30)),
    ]
    # Different days need no inter-day leg, so the accepted schedule itself is exact.
    assert result.confirmed


def test_fixed_window_is_explicit_user_duration_when_stay_missing():
    planner, _, _, stays = setup(stay=None)
    result = planner.plan(
        command(selection("pin", fixed_window=FixedWindow(day_no=1, start=time(10), end=time(10, 40))))
    )
    assert result.state.blocks[0].stay_min == 40
    assert stays.calls == 0


def test_duration_is_resolved_for_actual_candidate_date():
    planner, _, _, stays = setup(stay=None)

    def dated(ref, *, on_date):
        return 40 if on_date == date(2026, 11, 15) else None

    stays.get = dated
    result = planner.plan(command(selection("a"), days=2))
    assert result.confirmed
    assert result.state.blocks[0].day_no == 2
    assert result.state.blocks[0].stay_min == 40


def test_second_day_route_receives_second_day_kst():
    planner, _, routes, _ = setup()
    result = planner.plan(command(selection("a", allowed_days=(2,)), selection("b", allowed_days=(2,)), days=2))
    assert result.confirmed
    assert all(value.date() == date(2026, 11, 15) for value in routes.departures)
    assert all(value.utcoffset().total_seconds() == 32400 for value in routes.departures)


def test_insertion_resolving_direct_route_conflict_does_not_retain_stale_warning(monkeypatch):
    planner, places, routes, _ = setup()
    # FIRST_FEASIBLE can now keep an existing fixed conflict. Restrict C's
    # opening so this scenario exercises the gap that actually resolves it.
    places.hours[("c", date(2026, 11, 14))] = OpeningHours(open_time=time(10, 40), close_time=time(18))

    def estimate(origin, destination, *, mode, departure_at):
        pair = (origin.place_ref.place_id, destination.place_ref.place_id)
        duration = 60 if pair == ("a", "b") else 10
        return RouteEstimate(duration, "TMAP", datetime(2026, 11, 1, tzinfo=UTC), "prediction")

    monkeypatch.setattr(routes, "estimate_at", estimate)
    result = planner.plan(
        command(
            selection("a", fixed_window=FixedWindow(day_no=1, start=time(10), end=time(10, 30))),
            selection("b", fixed_window=FixedWindow(day_no=1, start=time(11), end=time(11, 30))),
            selection("c", stay_min=10),
        )
    )
    assert [(block.id, block.arrive_at, block.depart_at) for block in result.state.blocks] == [
        ("a", time(10), time(10, 30)),
        ("c", time(10, 40), time(10, 50)),
        ("b", time(11), time(11, 30)),
    ]
    assert result.confirmed
    assert not result.violations
    assert not result.conflicts
    assert not result.unplaced


def test_existing_fixed_conflict_does_not_block_other_flexible_slots():
    planner, _, _, _ = setup()
    result = planner.plan(
        command(
            selection("a", fixed_window=FixedWindow(day_no=1, start=time(10), end=time(10, 30))),
            selection("b", fixed_window=FixedWindow(day_no=1, start=time(10, 40), end=time(11, 10))),
            selection("d", fixed_window=FixedWindow(day_no=1, start=time(15), end=time(15, 30))),
            selection("c", stay_min=60),
        )
    )
    assert not result.unplaced
    assert {b.id for b in result.state.blocks} == {"a", "b", "c", "d"}
    assert not result.confirmed
    assert result.conflicts
    assert all("d" not in conflict.block_ids for conflict in result.conflicts)
    assert len([c for c in result.conflicts if c.block_ids == ("b",)]) == 1


def test_fixed_failure_is_not_inherited_by_next_fixed_block():
    planner, _, _, _ = setup()
    result = planner.plan(
        command(
            selection("a", fixed_window=FixedWindow(day_no=1, start=time(10), end=time(10, 30))),
            selection("b", fixed_window=FixedWindow(day_no=1, start=time(10, 40), end=time(11, 10))),
            selection("d", fixed_window=FixedWindow(day_no=1, start=time(15), end=time(15, 30))),
        )
    )
    assert all("d" not in conflict.block_ids for conflict in result.conflicts)
    assert len(result.conflicts) == 1


def test_flexible_visit_after_early_pin_starts_at_day_start():
    planner, _, _, _ = setup()
    result = planner.plan(
        command(
            selection("p", fixed_window=FixedWindow(day_no=1, start=time(7), end=time(7, 30))),
            selection("f"),
        )
    )
    flexible = next(b for b in result.state.blocks if b.id == "f")
    assert flexible.arrive_at == time(9)


@pytest.mark.parametrize("kakao", [False, True])
def test_unknown_hours_are_placed_but_not_confirmed(kakao):
    planner, places, _, _ = setup()
    places.hours[("a", date(2026, 11, 14))] = None
    item = selection("a", stay_min=30)
    if kakao:
        item = InitialSelection(
            block_id="a",
            place_ref=KakaoPlaceRef(kakao_place_id="123", kakao_place_url="https://place.map.kakao.com/123"),
            stay_min=30,
        )
    result = planner.plan(
        command(item),
        context=CalculationContext(session_coords={"123": SessionCoordinate(lat=35.987654, lng=129.876543)}),
    )
    assert not result.unplaced
    assert result.state.blocks[0].arrive_at == time(9)
    assert any(v.type == "HOURS_NEEDS_CHECK" for v in result.violations)
    assert not result.confirmed
    assert "35.987654" not in result.model_dump_json()


@pytest.mark.parametrize("allowed", [(1, 1), (2,), (1, 2)])
def test_invalid_allowed_days_are_rejected_without_silent_normalization(allowed):
    planner, _, _, _ = setup()
    with pytest.raises(ValueError):
        planner.plan(command(selection("a", allowed_days=allowed)))


def test_trial_cannot_worsen_an_existing_fixed_conflict():
    planner, places, _, _ = setup()
    # C fits only between A and B, but would worsen B's existing 5-minute delay.
    places.hours[("c", date(2026, 11, 14))] = OpeningHours(open_time=time(10, 30), close_time=time(11, 10))
    result = planner.plan(
        command(
            selection("a", fixed_window=FixedWindow(day_no=1, start=time(10), end=time(10, 30))),
            selection("b", fixed_window=FixedWindow(day_no=1, start=time(10, 40), end=time(11, 10))),
            selection("c", stay_min=20),
        )
    )
    assert [u.block_id for u in result.unplaced] == ["c"]
    assert [b.id for b in result.state.blocks] == ["a", "b"]


def test_route_memo_queries_each_pair_departure_once_per_plan(monkeypatch):
    planner, _, routes, _ = setup(stay=60)
    calls = []
    original = routes.estimate_at

    def tracking(origin, destination, *, mode, departure_at):
        key = (origin.place_ref.place_id, destination.place_ref.place_id, mode, departure_at)
        calls.append(key)
        return original(origin, destination, mode=mode, departure_at=departure_at)

    monkeypatch.setattr(routes, "estimate_at", tracking)
    request = command(*(selection(str(n)) for n in range(12)), days=2)
    result = planner.plan(request)
    first = list(calls)
    assert len(first) == len(set(first))
    assert len(first) <= 132  # n*(n-1), bounded fixture call regression, not a global quota policy
    assert result.state.blocks
    planner.plan(request)
    assert calls[len(first) :] == first  # no cross-request/shared memo


class CountingRoutes(Routes):
    """Counts every provider call so the per-plan lookup cap is observable."""

    def __init__(self):
        super().__init__()
        self.duration = 1
        self.calls = 0

    def estimate_at(self, origin, destination, *, mode, departure_at):
        self.calls += 1
        return super().estimate_at(origin, destination, mode=mode, departure_at=departure_at)


def counting_setup():
    routes = CountingRoutes()
    engine = BasicItineraryEngine(Places(), routes)
    return InitialSchedulePlanner(engine, Stays(10)), routes


def test_route_lookup_cap_holds_and_reports_remaining_flexible_selections():
    planner, routes = counting_setup()
    request = command(*[selection(f"s{i}") for i in range(MAX_INITIAL_SELECTIONS)], end=time(23))
    result = planner.plan(request)

    # Without the cap this request needs more than 300 lookups (insertion at gap 0 shifts every later leg).
    assert routes.calls == MAX_ROUTE_LOOKUPS_PER_PLAN == 300
    assert result.unplaced and not result.confirmed
    assert {item.reason.type for item in result.unplaced} == {"PLACEMENT_NEEDS_CHECK"}
    placed = [block.id for block in result.state.blocks]
    unplaced = [item.block_id for item in result.unplaced]
    # Caller order: everything after the first budget miss is reported, nothing is lost or duplicated.
    assert sorted(placed + unplaced) == sorted(f"s{i}" for i in range(MAX_INITIAL_SELECTIONS))
    assert unplaced == [f"s{i}" for i in range(len(placed), MAX_INITIAL_SELECTIONS)]


def test_small_route_lookup_cap_stops_further_placement(monkeypatch):
    monkeypatch.setattr(initial, "MAX_ROUTE_LOOKUPS_PER_PLAN", 2)
    planner, routes = counting_setup()
    result = planner.plan(command(selection("a"), selection("b"), selection("c"), selection("d")))
    assert routes.calls == 2
    assert sorted(block.id for block in result.state.blocks) == ["a", "b"]
    assert [(item.block_id, item.reason.type) for item in result.unplaced] == [
        ("c", "PLACEMENT_NEEDS_CHECK"),
        ("d", "PLACEMENT_NEEDS_CHECK"),
    ]


def test_fixed_selections_exhausting_cap_are_not_silently_dropped(monkeypatch):
    monkeypatch.setattr(initial, "MAX_ROUTE_LOOKUPS_PER_PLAN", 0)
    planner, _ = counting_setup()
    fixed = [
        selection(key, stay_min=30, fixed_window=FixedWindow(day_no=1, start=time(hour), end=time(hour, 30)))
        for key, hour in (("a", 10), ("b", 12))
    ]
    with pytest.raises(NeedsConfirmationError):
        planner.plan(command(*fixed))


def test_provider_failures_are_logged_with_type_and_place_reference_only(caplog):
    secret = "synthetic-key 35.9876543,129.9876543 private-body"

    class FailingPlaces(Places):
        def get(self, ref, *, on_date):
            if ref.place_id == "broken":
                raise RuntimeError(secret)
            return super().get(ref, on_date=on_date)

    class FailingStays:
        def get(self, place_ref, *, on_date):
            raise ValueError(secret)

    engine = BasicItineraryEngine(FailingPlaces(), Routes())
    planner = InitialSchedulePlanner(engine, FailingStays(), tag_stays=FailingStays())
    caplog.set_level("WARNING", logger="app.modules.engine.initial")
    planner.plan(command(selection("broken", stay_min=30), selection("nostay")))

    assert "initial_place_lookup failed error=RuntimeError kind=PUBLIC" in caplog.text
    assert "initial_stay_lookup failed error=ValueError kind=PUBLIC" in caplog.text
    assert "initial_tag_stay_lookup failed error=ValueError kind=PUBLIC" in caplog.text
    assert "broken" not in caplog.text and "nostay" not in caplog.text
    for leaked in ("35.9876543", "129.9876543", "synthetic-key", "private-body", "35.123", "129.123"):
        assert leaked not in caplog.text


def test_request_place_id_never_reaches_failure_log(caplog):
    forged = "SYNTHETIC_USER_TEXT\nFORGED_LOG_ENTRY"

    class FailingPlaces(Places):
        def get(self, ref, *, on_date):
            raise RuntimeError("lookup failed")

    planner = InitialSchedulePlanner(BasicItineraryEngine(FailingPlaces(), Routes()), Stays())
    caplog.set_level("WARNING", logger="app.modules.engine.initial")
    planner.plan(command(selection(forged, stay_min=30)))

    assert "initial_place_lookup failed error=RuntimeError kind=PUBLIC" in caplog.text
    assert "SYNTHETIC_USER_TEXT" not in caplog.text and "FORGED_LOG_ENTRY" not in caplog.text
    assert all(len(record.getMessage().splitlines()) == 1 for record in caplog.records)


# FR-009 혼잡 회피 배치(AC-010, 결정 D1: 같은 날 안 삽입 위치만 고른다)

DAY1 = date(2026, 11, 14)


def crowd_of(scores, confidence="높음"):
    return PlaceCrowdResponse(
        hours=[CrowdHour(h=h, score=score) for h, score in scores.items()],
        confidence=confidence,
        as_of=datetime(2026, 11, 1, tzinfo=UTC),
        sources=["synthetic"],
    )


# x 는 오전(10~12시) 붐빔, 오후(13~14시) 여유
X_MORNING_BUSY = {10: 0.9, 11: 0.9, 12: 0.9, 13: 0.2, 14: 0.2}


class FakeCrowd:
    def __init__(self, by_place=None, error=None):
        self.by_place = by_place or {}
        self.error = error
        self.calls = []

    def crowd(self, place_ref, *, on_date):
        self.calls.append((place_ref.place_id, on_date))
        if self.error is not None:
            raise self.error
        return self.by_place.get(place_ref.place_id)


def crowd_setup(crowd=None, avoidance=None):
    places, routes = Places(), Routes()
    planner = InitialSchedulePlanner(BasicItineraryEngine(places, routes), Stays(), crowd=crowd, avoidance=avoidance)
    return planner, places, routes


def pin_then_two():
    # 고정 a(10:00~10:30) 앞에는 2시간 체류가 들어가지 않는다. y 는 a 뒤(10:45~12:45),
    # x 의 수락 위치는 a 와 y 사이(10:45~12:45) 또는 y 뒤(13:00~15:00) 두 곳이다.
    return command(
        selection("a", fixed_window=FixedWindow(day_no=1, start=time(10), end=time(10, 30))),
        selection("y", stay_min=120),
        selection("x", stay_min=120),
    )


def times(result):
    return {block.id: (block.arrive_at, block.depart_at) for block in result.state.blocks}


def test_flexible_block_moves_to_less_crowded_gap_and_pin_stays():
    baseline = crowd_setup()[0].plan(pin_then_two())
    assert times(baseline)["x"] == (time(10, 45), time(12, 45))

    crowd = FakeCrowd({"x": crowd_of(X_MORNING_BUSY)})
    result = crowd_setup(crowd)[0].plan(pin_then_two())

    assert times(result)["x"] == (time(13), time(15))
    assert times(result)["a"] == times(baseline)["a"] == (time(10), time(10, 30))
    assert [block.id for block in result.state.blocks] == ["a", "y", "x"]
    assert not result.unplaced and result.confirmed
    # 고정 블록은 혼잡을 조회하지 않는다. 미고정 블록만 그 날짜로 조회한다.
    assert crowd.calls == [("y", DAY1), ("x", DAY1)]


@pytest.mark.parametrize(
    "crowd",
    [
        None,
        CrowdServiceLookup(CrowdService()),  # 운영 기본: 파일 없음 → 정보 부족
        FakeCrowd(),
        FakeCrowd({"x": crowd_of(X_MORNING_BUSY, "낮음"), "y": crowd_of(X_MORNING_BUSY, "낮음")}),
        FakeCrowd(error=RuntimeError("crowd down")),
    ],
    ids=["not-injected", "empty-provider", "no-data", "low-confidence", "lookup-error"],
)
@pytest.mark.parametrize(
    "request_factory",
    [lambda: command(selection("a"), selection("b"), selection("c")), pin_then_two],
    ids=["reproducible", "pin-then-two"],
)
def test_without_usable_crowd_output_equals_current_behavior(crowd, request_factory):
    expected_planner, _, expected_routes = crowd_setup()
    expected = expected_planner.plan(request_factory())
    planner, _, routes = crowd_setup(crowd)
    assert planner.plan(request_factory()) == expected
    # 추가 위치 평가도 하지 않는다(경로 조회가 그대로).
    assert routes.departures == expected_routes.departures


def test_crowd_lookup_failure_is_logged_without_place_reference(caplog):
    caplog.set_level("WARNING", logger="app.modules.engine.initial")
    crowd_setup(FakeCrowd(error=RuntimeError("secret-body")))[0].plan(pin_then_two())
    assert "initial_crowd_lookup failed error=RuntimeError kind=PUBLIC" in caplog.text
    assert "secret-body" not in caplog.text


def test_less_crowded_gap_after_closing_is_not_chosen():
    planner, places, _ = crowd_setup(FakeCrowd({"x": crowd_of(X_MORNING_BUSY)}))
    places.hours[("x", DAY1)] = OpeningHours(open_time=time(8), close_time=time(14))
    result = planner.plan(pin_then_two())
    assert times(result)["x"] == (time(10, 45), time(12, 45))
    assert result.confirmed


def test_small_crowd_difference_keeps_first_gap():
    scores = {10: 0.5, 11: 0.5, 12: 0.5, 13: 0.45, 14: 0.45}
    planner = crowd_setup(FakeCrowd({"x": crowd_of(scores)}))[0]
    assert times(planner.plan(pin_then_two()))["x"] == (time(10, 45), time(12, 45))
    # 최소 이득은 설정값이다.
    relaxed = crowd_setup(FakeCrowd({"x": crowd_of(scores)}), AvoidanceSettings(min_gain=0.05))[0]
    assert times(relaxed.plan(pin_then_two()))["x"] == (time(13), time(15))


def test_low_confidence_moves_only_when_configured():
    crowd = FakeCrowd({"x": crowd_of(X_MORNING_BUSY, "낮음")})
    planner = crowd_setup(crowd, AvoidanceSettings(min_confidence="낮음"))[0]
    assert times(planner.plan(pin_then_two()))["x"] == (time(13), time(15))


def test_budget_exhausted_mid_evaluation_places_with_collected_gaps(monkeypatch):
    # 첫 통과(혼잡 없음)가 5건을 쓴다: y 위치 0·1 → 2건, x 위치 0 → 1건, 위치 1 → 2건.
    # 혼잡 통과는 캐시를 재사용하고, x 위치 2(y→x) 의 새 조회에서 한도에 닿는다.
    monkeypatch.setattr(initial, "MAX_ROUTE_LOOKUPS_PER_PLAN", 5)
    planner, _, routes = crowd_setup(FakeCrowd({"x": crowd_of(X_MORNING_BUSY)}))
    result = planner.plan(pin_then_two())

    assert len(routes.departures) == 5
    # 이미 모은 위치(a 와 y 사이)로 배치한다. 배치 가능한 블록을 버리지 않는다.
    assert times(result)["x"] == (time(10, 45), time(12, 45))
    assert not result.unplaced


def placed_count(result):
    return len(result.state.blocks)


@pytest.mark.parametrize("limit", [3, 5, 6, 8, 10, 12])
def test_near_exhausted_budget_places_as_many_blocks_as_without_crowd(monkeypatch, limit):
    monkeypatch.setattr(initial, "MAX_ROUTE_LOOKUPS_PER_PLAN", limit)
    request = pin_then_two().model_copy(
        update={"selections": (*pin_then_two().selections, selection("z", stay_min=30), selection("w", stay_min=30))}
    )
    crowd = FakeCrowd({key: crowd_of(X_MORNING_BUSY) for key in ("x", "y", "z", "w")})
    planner, _, routes = crowd_setup(crowd)
    result = planner.plan(request)
    expected = crowd_setup()[0].plan(request)

    assert len(routes.departures) <= limit
    assert placed_count(result) == placed_count(expected)
    assert len(result.unplaced) == len(expected.unplaced)


def test_route_lookup_cap_holds_with_crowd_comparison():
    routes = CountingRoutes()
    everyone = {f"s{i}": crowd_of({h: 0.5 for h in range(9, 23)}) for i in range(MAX_INITIAL_SELECTIONS)}
    planner = InitialSchedulePlanner(BasicItineraryEngine(Places(), routes), Stays(10), crowd=FakeCrowd(everyone))
    request = command(*[selection(f"s{i}") for i in range(MAX_INITIAL_SELECTIONS)], end=time(23))
    result = planner.plan(request)

    assert routes.calls == MAX_ROUTE_LOOKUPS_PER_PLAN
    expected = counting_setup()[0].plan(request)
    assert placed_count(result) == placed_count(expected)
    placed = [block.id for block in result.state.blocks]
    unplaced = [item.block_id for item in result.unplaced]
    assert sorted(placed + unplaced) == sorted(f"s{i}" for i in range(MAX_INITIAL_SELECTIONS))


def review_repro():
    # #63 리뷰 재현: y(60분), x(120분, 13:15 마감, 오전 붐빔), z(60분, 10:30 마감) 순서로 넣는다.
    return command(selection("y", stay_min=60), selection("x", stay_min=120), selection("z", stay_min=60))


def repro_setup(crowd=None):
    planner, places, routes = crowd_setup(crowd)
    places.hours[("x", DAY1)] = OpeningHours(open_time=time(8), close_time=time(13, 15))
    places.hours[("z", DAY1)] = OpeningHours(open_time=time(8), close_time=time(10, 30))
    return planner, routes


def test_crowd_never_makes_a_placeable_block_unplaced(caplog):
    caplog.set_level("INFO", logger="app.modules.engine.initial")
    planner, routes = repro_setup()
    expected = planner.plan(review_repro())
    assert [block.id for block in expected.state.blocks] == ["z", "x", "y"] and not expected.unplaced
    assert len(routes.departures) == 3

    # x 만 보면 y 뒤(10:15~)가 덜 붐비지만, 그러면 z 를 넣을 수 없다 → 첫 수락 결과를 쓴다.
    crowd = FakeCrowd({"x": crowd_of({9: 0.9, 10: 0.9, 11: 0.2, 12: 0.2, 13: 0.2})})
    planner, routes = repro_setup(crowd)
    result = planner.plan(review_repro())
    assert result == expected
    # 첫 통과 3건 + 혼잡 통과의 새 조합 5건. 이미 조회한 구간은 다시 조회하지 않는다.
    assert len(routes.departures) == 8
    assert "initial_crowd_avoidance usable=1 applied=False" in caplog.text


def outcome(placed, unplaced=(), conflict_ids=()):
    blocks = tuple(day_option(time(10), feasible=True, block_id=key)[1].blocks[0] for key in placed)
    reason = Violation(type="PLACEMENT_NEEDS_CHECK", cause="synthetic")
    return InitialScheduleResult(
        state=ScheduleState(blocks=blocks),
        unplaced=tuple(UnplacedSelection(block_id=key, reason=reason) for key in unplaced),
        violations=tuple(reason for _ in unplaced),
        conflicts=(ScheduleConflict(cause="synthetic", block_ids=conflict_ids),) if conflict_ids else (),
    )


def test_crowd_plan_must_not_swap_which_selection_is_unplaced():
    baseline = outcome(["a", "b"], unplaced=["c"])
    # 같은 수(배치 2·미배치 1)라도 사용자가 고른 a 를 빼고 c 를 넣으면 쓰지 않는다.
    assert not InitialSchedulePlanner._not_worse(outcome(["b", "c"], unplaced=["a"]), baseline)
    assert InitialSchedulePlanner._not_worse(outcome(["b", "a"], unplaced=["c"]), baseline)
    assert InitialSchedulePlanner._not_worse(outcome(["a", "b", "c"]), baseline)


def test_crowd_plan_must_not_move_a_conflict_onto_another_block():
    baseline = outcome(["a", "b"], conflict_ids=("a",))
    assert not InitialSchedulePlanner._not_worse(outcome(["a", "b"], conflict_ids=("b",)), baseline)
    assert InitialSchedulePlanner._not_worse(outcome(["b", "a"], conflict_ids=("a",)), baseline)


def test_crowd_result_is_never_worse_than_first_feasible():
    for request in (pin_then_two(), review_repro()):
        expected = repro_setup()[0].plan(request)
        crowd = FakeCrowd({key: crowd_of(X_MORNING_BUSY) for key in ("x", "y", "z")})
        result = repro_setup(crowd)[0].plan(request)
        assert placed_count(result) >= placed_count(expected)
        assert len(result.unplaced) <= len(expected.unplaced)
        assert len(result.conflicts) <= len(expected.conflicts)
        assert len(result.violations) <= len(expected.violations)
        assert result.confirmed or not expected.confirmed


class PairRoutes(Routes):
    def __init__(self, slow):
        super().__init__()
        self.slow = slow

    def estimate_at(self, origin, destination, *, mode, departure_at):
        self.departures.append(departure_at)
        pair = (origin.place_ref.place_id, destination.place_ref.place_id)
        return RouteEstimate(self.slow.get(pair, 15), "TMAP", datetime(2026, 11, 1, tzinfo=UTC), "prediction")


@pytest.mark.parametrize(("limit", "expected_x"), [(15, time(10, 45)), (30, time(13, 25))])
def test_crowd_gap_with_too_much_extra_travel_is_not_chosen(limit, expected_x):
    # y→x 가 40분이면 오후 위치의 그 날 이동시간이 25분 늘어난다.
    routes = PairRoutes({("y", "x"): 40})
    planner = InitialSchedulePlanner(
        BasicItineraryEngine(Places(), routes),
        Stays(),
        crowd=FakeCrowd({"x": crowd_of(X_MORNING_BUSY)}),
        avoidance=AvoidanceSettings(max_extra_travel_min=limit),
    )
    assert times(planner.plan(pin_then_two()))["x"][0] == expected_x


def test_max_positions_limits_compared_gaps():
    crowd = FakeCrowd({"x": crowd_of(X_MORNING_BUSY)})
    planner, _, routes = crowd_setup(crowd, AvoidanceSettings(max_positions=0))
    assert times(planner.plan(pin_then_two()))["x"] == (time(10, 45), time(12, 45))
    expected_planner, _, expected_routes = crowd_setup()
    expected_planner.plan(pin_then_two())
    # 첫 수락 위치 뒤를 보지 않으므로 새 경로 조회가 없다.
    assert routes.departures == expected_routes.departures


def day_option(arrive, *, feasible, block_id="x"):
    block = StoredBlock(
        id=block_id,
        day_no=1,
        seq=1,
        place_ref=PublicPlaceRef(place_id=block_id),
        is_fixed=False,
        stay_min=60,
        arrive_at=arrive,
        depart_at=time(arrive.hour + 1, arrive.minute),
        origin="USER",
    )
    return [], initial._Day((block,), (), feasible, feasible)


def test_conflict_preserving_gap_does_not_beat_a_feasible_first_gap():
    planner = crowd_setup()[0]
    crowd = crowd_of(X_MORNING_BUSY)
    options = [day_option(time(10), feasible=True), day_option(time(13), feasible=False)]
    assert planner._less_crowded(crowd, "x", options) == 0
    # 첫 위치도 충돌을 안고 있으면(둘 다 불가능) 혼잡으로 고를 수 있다.
    options = [day_option(time(10), feasible=False), day_option(time(13), feasible=False)]
    assert planner._less_crowded(crowd, "x", options) == 1
    options = [day_option(time(10), feasible=True), day_option(time(13), feasible=True)]
    assert planner._less_crowded(crowd, "x", options) == 1
