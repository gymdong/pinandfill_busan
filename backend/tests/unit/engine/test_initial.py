"""Synthetic, network-free initial scheduling acceptance cases."""

from datetime import UTC, date, datetime, time

import pytest
from pydantic import ValidationError

from app.modules.engine.initial import InitialScheduleCommand, InitialSchedulePlanner, InitialSelection
from app.modules.engine.interfaces import RouteEstimate
from app.modules.engine.schemas import (
    CalculationContext,
    FixedWindow,
    KakaoPlaceRef,
    OpeningHours,
    PublicPlaceRef,
    SessionCoordinate,
    TransientPlaceDetails,
    TripWindow,
)
from app.modules.engine.service import BasicItineraryEngine
from app.modules.trips.schemas import Schedule


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
    planner, _, routes, _ = setup()

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
