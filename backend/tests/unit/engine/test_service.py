import json
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from typing import Literal

import pytest

from app.modules.engine.interfaces import RouteEstimate
from app.modules.engine.schemas import (
    BlockDraft,
    CalculationContext,
    FixedWindow,
    InsertInput,
    KakaoPlaceRef,
    OpeningHours,
    PublicPlaceRef,
    RecomputeInput,
    ScheduleState,
    SessionCoordinate,
    StoredBlock,
    StoredLeg,
    TransientPlaceDetails,
    TripWindow,
    ValidateInput,
    ValidationResult,
)
from app.modules.engine.service import (
    BasicItineraryEngine,
    EngineInputError,
    NeedsConfirmationError,
    PolicyRequiredError,
)


class FakePlaces:
    def __init__(self, details: dict[str, TransientPlaceDetails]) -> None:
        self.details = details
        self.calls: list[str] = []

    def get(self, place_ref: PublicPlaceRef | KakaoPlaceRef, *, on_date: date) -> TransientPlaceDetails:
        del on_date
        assert isinstance(place_ref, PublicPlaceRef), "Kakao places must never reach the public provider"
        self.calls.append(place_ref.place_id)
        return self.details[place_ref.place_id]


class FakeRoutes:
    def __init__(self, duration_min: int = 15) -> None:
        self.duration_min = duration_min
        self.calls: list[tuple[str, str]] = []

    def estimate(
        self,
        origin: TransientPlaceDetails,
        destination: TransientPlaceDetails,
        *,
        mode: Literal["TRANSIT", "CAR", "WALK"],
    ) -> RouteEstimate:
        del mode
        assert origin.lat is not None and origin.lng is not None
        assert destination.lat is not None and destination.lng is not None
        self.calls.append((_ref_id(origin), _ref_id(destination)))
        return RouteEstimate(
            duration_min=self.duration_min,
            source="ESTIMATED",
            computed_at=datetime(2026, 11, 2, 1, tzinfo=UTC),
        )


def _ref_id(details: TransientPlaceDetails) -> str:
    ref = details.place_ref
    return ref.place_id if isinstance(ref, PublicPlaceRef) else ref.kakao_place_id


def _trip(*, end_date: date = date(2026, 11, 2), day_end: time = time(23, 59)) -> TripWindow:
    return TripWindow(
        start_date=date(2026, 11, 2),
        end_date=end_date,
        day_start=time(8),
        day_end=day_end,
        transport_mode="TRANSIT",
    )


def _public_ref(place_id: str) -> PublicPlaceRef:
    return PublicPlaceRef(place_id=place_id)


def _details(
    place_id: str,
    *,
    hours: OpeningHours | None = None,
    lat: float | None = 35.1,
    lng: float | None = 129.1,
    complete_display: bool = True,
) -> TransientPlaceDetails:
    return TransientPlaceDetails(
        place_ref=_public_ref(place_id),
        name=f"합성 장소 {place_id}" if complete_display else None,
        lat=lat,
        lng=lng,
        category="synthetic" if complete_display else None,
        ref_date=date(2026, 11, 1) if complete_display else None,
        hours=hours,
    )


def _open_hours() -> OpeningHours:
    return OpeningHours(open_time=time(8), close_time=time(23, 59))


def _block(
    block_id: str,
    seq: int,
    *,
    place_id: str | None = None,
    ref: PublicPlaceRef | KakaoPlaceRef | None = None,
    arrive: time | None,
    depart: time | None,
    stay: int = 30,
    fixed: bool = False,
    day_no: int = 1,
) -> StoredBlock:
    place_ref = ref or _public_ref(place_id or block_id)
    return StoredBlock(
        id=block_id,
        day_no=day_no,
        seq=seq,
        place_ref=place_ref,
        is_fixed=fixed,
        fixed_start=arrive if fixed else None,
        fixed_end=depart if fixed else None,
        stay_min=stay,
        arrive_at=arrive,
        depart_at=depart,
        origin="USER",
    )


def _engine(
    place_ids: tuple[str, ...],
    *,
    duration: int = 15,
    details_factory: Callable[[str], TransientPlaceDetails] | None = None,
) -> tuple[BasicItineraryEngine, FakePlaces, FakeRoutes]:
    factory = details_factory or (lambda place_id: _details(place_id, hours=_open_hours()))
    places = FakePlaces({place_id: factory(place_id) for place_id in place_ids})
    routes = FakeRoutes(duration)
    ids = iter(f"generated-{index}" for index in range(20))
    engine = BasicItineraryEngine(
        places,
        routes,
        clock=lambda: datetime(2026, 11, 2, 1, tzinfo=UTC),
        id_factory=lambda: next(ids),
    )
    return engine, places, routes


def _warning_types(result: ValidationResult, block_id: str) -> set[str]:
    return {warning.type for warning in result.block_warnings.get(block_id, ())}


def test_recompute_preserves_prefix_fixed_sequence_and_applies_travel_plus_stay() -> None:
    engine, _, routes = _engine(("a", "b", "c", "d"), duration=20)
    state = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 20, arrive=time(9, 50), depart=time(10, 20)),
            _block("c", 30, arrive=time(11), depart=time(11, 30), fixed=True),
            _block("d", 10, arrive=time(9), depart=time(9, 30), fixed=True, day_no=2),
        )
    )

    result = engine.recompute(RecomputeInput(trip=_trip(end_date=date(2026, 11, 3)), schedule=state, from_block_id="a"))

    assert result.state.blocks[0] == state.blocks[0]
    assert [(block.id, block.seq) for block in result.state.blocks] == [
        ("a", 10),
        ("b", 20),
        ("c", 30),
        ("d", 10),
    ]
    assert (result.state.blocks[1].arrive_at, result.state.blocks[1].depart_at) == (time(9, 50), time(10, 20))
    assert (result.state.blocks[2].arrive_at, result.state.blocks[2].depart_at) == (time(11), time(11, 30))
    assert result.state.blocks[3] == state.blocks[3]
    assert routes.calls == [("a", "b"), ("b", "c")]


def test_recompute_reports_fixed_arrival_that_travel_time_cannot_reach() -> None:
    engine, _, _ = _engine(("a", "b"), duration=45)
    state = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 20, arrive=time(10), depart=time(10, 30), fixed=True),
        )
    )

    result = engine.recompute(RecomputeInput(trip=_trip(), schedule=state, from_block_id="a"))

    assert result.state.blocks[1].arrive_at == time(10)
    assert "TRAVEL_TIME_CONFLICT" in {violation.type for violation in result.schedule.violations}
    assert any(conflict.block_ids == ("b",) for conflict in result.schedule.conflicts)


@pytest.mark.parametrize(
    ("hours", "arrive", "depart", "expected"),
    [
        (OpeningHours(open_time=time(10), close_time=time(18)), time(9), time(9, 30), "OPENING_HOURS"),
        (OpeningHours(is_closed=True), time(10), time(10, 30), "CLOSED_DAY"),
        (
            OpeningHours(
                open_time=time(9),
                close_time=time(18),
                break_start=time(12),
                break_end=time(13),
            ),
            time(12, 30),
            time(13),
            "BREAK_TIME",
        ),
        (None, time(10), time(10, 30), "HOURS_NEEDS_CHECK"),
    ],
)
def test_validation_chain_checks_open_closed_break_and_unknown_hours(
    hours: OpeningHours | None,
    arrive: time,
    depart: time,
    expected: str,
) -> None:
    engine, _, _ = _engine(("a",), details_factory=lambda place_id: _details(place_id, hours=hours))
    state = ScheduleState(blocks=(_block("a", 10, arrive=arrive, depart=depart),))

    validation = engine.validate(ValidateInput(trip=_trip(), schedule=state))

    assert expected in _warning_types(validation, "a")


def test_missing_kakao_coords_skips_route_and_marks_leg_unknown() -> None:
    kakao = KakaoPlaceRef(
        kakao_place_id="21362956",
        kakao_place_url="https://place.map.kakao.com/21362956",
    )
    engine, places, routes = _engine(("a",))
    state = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("k", 20, ref=kakao, arrive=None, depart=None),
        )
    )

    result = engine.recompute(RecomputeInput(trip=_trip(), schedule=state, from_block_id="a"))

    assert places.calls == ["a"]
    assert routes.calls == []
    assert result.state.legs[0].duration_min is None
    assert "COORDS_NEEDS_CHECK" in {warning.type for warning in result.schedule.days[0].blocks[1].warnings}
    assert "TRAVEL_TIME_NEEDS_CHECK" in {warning.type for warning in result.schedule.days[0].blocks[1].warnings}


def test_kakao_coords_are_request_scoped_need_no_name_and_are_not_serialized_or_logged(caplog) -> None:
    kakao = KakaoPlaceRef(
        kakao_place_id="21362956",
        kakao_place_url="https://place.map.kakao.com/21362956",
    )
    engine, _, routes = _engine(("a",), duration=15)
    state = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("k", 20, ref=kakao, arrive=None, depart=None),
        )
    )
    secret_lat = 35.123456
    context = CalculationContext(session_coords={"21362956": SessionCoordinate(lat=secret_lat, lng=129.654321)})

    result = engine.recompute(
        RecomputeInput(trip=_trip(), schedule=state, from_block_id="a"),
        context=context,
    )

    assert routes.calls == [("a", "21362956")]
    assert (result.state.blocks[1].arrive_at, result.state.blocks[1].depart_at) == (time(9, 45), time(10, 15))
    combined = json.dumps(
        {
            "state": result.state.model_dump(mode="json", by_alias=True),
            "response": result.schedule.model_dump(mode="json", by_alias=True),
        },
        ensure_ascii=False,
    )
    assert str(secret_lat) not in combined
    assert str(secret_lat) not in caplog.text
    assert result.schedule.days[0].blocks[1].place.model_dump(mode="json", by_alias=True) == {
        "kakaoPlaceId": "21362956",
        "placeUrl": "https://place.map.kakao.com/21362956",
        "source": "KAKAO",
    }

    calls_before = len(routes.calls)
    without_context = engine.recompute(RecomputeInput(trip=_trip(), schedule=state, from_block_id="a"))
    assert len(routes.calls) == calls_before
    assert without_context.state.legs[0].duration_min is None


def test_insert_uses_explicit_adjacent_gap_without_renumbering_existing_blocks() -> None:
    engine, _, _ = _engine(("a", "new", "b"), duration=15)
    original = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 20, arrive=time(10, 30), depart=time(11), fixed=True),
        )
    )
    command = InsertInput(
        trip=_trip(),
        schedule=original,
        block=BlockDraft(
            place_ref=_public_ref("new"),
            is_fixed=False,
            stay_min=30,
            origin="SUGGESTED",
        ),
        from_block_id="a",
        to_block_id="b",
        block_id="new",
    )

    result = engine.insert(command)

    assert [(block.id, block.seq) for block in result.state.blocks] == [("a", 10), ("new", 11), ("b", 20)]
    assert (result.state.blocks[1].arrive_at, result.state.blocks[1].depart_at) == (time(9, 45), time(10, 15))
    assert (result.state.blocks[2].arrive_at, result.state.blocks[2].depart_at) == (time(10, 30), time(11))


def test_wrong_adjacency_rejects_without_mutating_input() -> None:
    engine, _, _ = _engine(("a", "b", "c", "new"))
    original = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30)),
            _block("b", 20, arrive=time(10), depart=time(10, 30)),
            _block("c", 30, arrive=time(11), depart=time(11, 30)),
        )
    )
    before = original.model_dump(mode="json", by_alias=True)
    command = InsertInput(
        trip=_trip(),
        schedule=original,
        block=BlockDraft(place_ref=_public_ref("new"), is_fixed=False, stay_min=30, origin="USER"),
        from_block_id="a",
        to_block_id="c",
    )

    with pytest.raises(EngineInputError, match="adjacent"):
        engine.insert(command)

    assert original.model_dump(mode="json", by_alias=True) == before


def test_insert_without_slot_requires_unsettled_policy() -> None:
    engine, _, _ = _engine(("a", "b", "new"))
    state = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30)),
            _block("b", 20, arrive=time(10), depart=time(10, 30)),
        )
    )
    command = InsertInput(
        trip=_trip(),
        schedule=state,
        block=BlockDraft(place_ref=_public_ref("new"), is_fixed=False, stay_min=30, origin="USER"),
    )

    with pytest.raises(PolicyRequiredError, match="position"):
        engine.insert(command)


def test_insert_without_sequence_gap_renumbers_same_day_and_preserves_fixed_data() -> None:
    engine, _, _ = _engine(("a", "b", "new", "next-day"))
    state = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 11, arrive=time(10), depart=time(10, 30), fixed=True),
            _block("next-day", 99, arrive=time(11), depart=time(11, 30), fixed=True, day_no=2),
        )
    )
    command = InsertInput(
        trip=_trip(end_date=date(2026, 11, 3)),
        schedule=state,
        block=BlockDraft(place_ref=_public_ref("new"), is_fixed=False, stay_min=30, origin="USER"),
        from_block_id="a",
        to_block_id="b",
        block_id="new",
    )

    result = engine.insert(command)

    assert [(block.id, block.seq) for block in result.state.blocks] == [
        ("a", 10),
        ("new", 20),
        ("b", 30),
        ("next-day", 99),
    ]
    assert result.state.blocks[0] == state.blocks[0]
    assert (result.state.blocks[2].fixed_start, result.state.blocks[2].fixed_end) == (time(10), time(10, 30))
    assert (result.state.blocks[2].arrive_at, result.state.blocks[2].depart_at) == (time(10), time(10, 30))
    assert result.state.blocks[3] == state.blocks[2]


def test_insert_uses_new_gap_after_renumbering_without_changing_existing_order() -> None:
    engine, _, _ = _engine(("a", "b", "first", "second"))
    initial = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 11, arrive=time(11), depart=time(11, 30), fixed=True),
        )
    )
    first = engine.insert(
        InsertInput(
            trip=_trip(),
            schedule=initial,
            block=BlockDraft(place_ref=_public_ref("first"), is_fixed=False, stay_min=30, origin="USER"),
            from_block_id="a",
            to_block_id="b",
            block_id="first",
        )
    ).state

    second = engine.insert(
        InsertInput(
            trip=_trip(),
            schedule=first,
            block=BlockDraft(place_ref=_public_ref("second"), is_fixed=False, stay_min=30, origin="USER"),
            from_block_id="a",
            to_block_id="first",
            block_id="second",
        )
    ).state

    assert [(block.id, block.seq) for block in second.blocks] == [
        ("a", 10),
        ("second", 11),
        ("first", 20),
        ("b", 30),
    ]
    assert second.blocks[0] == initial.blocks[0]
    assert second.blocks[3].id == initial.blocks[1].id
    assert (second.blocks[3].fixed_start, second.blocks[3].fixed_end) == (time(11), time(11, 30))


def test_recompute_reports_day_overflow_without_assigning_cross_day_times() -> None:
    engine, _, _ = _engine(("a", "b"), duration=20)
    state = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(23), depart=time(23, 30), fixed=True),
            _block("b", 20, arrive=None, depart=None, stay=30),
        )
    )

    result = engine.recompute(RecomputeInput(trip=_trip(), schedule=state, from_block_id="a"))

    assert result.state.blocks[1].arrive_at is None
    assert "DAY_OVERFLOW" in {warning.type for warning in result.schedule.days[0].blocks[1].warnings}
    assert any(conflict.block_ids == ("b",) for conflict in result.schedule.conflicts)


def test_missing_public_display_fields_require_confirmation() -> None:
    engine, _, _ = _engine(
        ("a", "b"),
        details_factory=lambda place_id: _details(
            place_id,
            hours=_open_hours(),
            complete_display=False,
        ),
    )
    state = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 20, arrive=None, depart=None),
        )
    )

    with pytest.raises(NeedsConfirmationError, match="display information"):
        engine.recompute(RecomputeInput(trip=_trip(), schedule=state, from_block_id="a"))


def test_block_day_must_be_inside_trip_date_range() -> None:
    engine, _, _ = _engine(("a",))
    state = ScheduleState(blocks=(_block("a", 10, arrive=time(9), depart=time(9, 30), day_no=2),))

    with pytest.raises(EngineInputError, match="outside the trip dates"):
        engine.validate(ValidateInput(trip=_trip(), schedule=state))


def test_fixed_insert_keeps_designated_window_and_sequence() -> None:
    engine, _, _ = _engine(("a", "fixed", "b"), duration=15)
    state = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 20, arrive=time(11), depart=time(11, 30), fixed=True),
        )
    )
    command = InsertInput(
        trip=_trip(),
        schedule=state,
        block=BlockDraft(
            place_ref=_public_ref("fixed"),
            is_fixed=True,
            fixed_window=FixedWindow(day_no=1, start=time(10), end=time(10, 30)),
            stay_min=30,
            origin="USER",
        ),
        from_block_id="a",
        to_block_id="b",
        block_id="fixed",
    )

    result = engine.insert(command)

    inserted = result.state.blocks[1]
    assert (inserted.seq, inserted.fixed_start, inserted.fixed_end) == (11, time(10), time(10, 30))
    assert (inserted.arrive_at, inserted.depart_at) == (time(10), time(10, 30))


def test_middle_anchor_preserves_prefix_legs_other_days_and_repeated_fixed_times() -> None:
    engine, _, routes = _engine(("prefix", "anchor", "fixed", "next-day"))
    prefix_leg = StoredLeg(
        id="prefix-leg",
        from_block_id="prefix",
        to_block_id="anchor",
        mode="TRANSIT",
        duration_min=15,
        source="ESTIMATED",
        computed_at=datetime(2026, 11, 2, tzinfo=UTC),
    )
    original = ScheduleState(
        blocks=(
            _block("prefix", 10, arrive=time(8), depart=time(8, 30), fixed=True),
            _block("anchor", 20, arrive=time(9), depart=time(9, 30)),
            _block("fixed", 30, arrive=time(10), depart=time(10, 30), fixed=True),
            _block("next-day", 10, arrive=time(9), depart=time(9, 30), fixed=True, day_no=2),
        ),
        legs=(prefix_leg,),
    )
    state = original
    for _ in range(10):
        state = engine.recompute(
            RecomputeInput(
                trip=_trip(end_date=date(2026, 11, 3)),
                schedule=state,
                from_block_id="anchor",
            )
        ).state
        assert state.blocks == original.blocks
        assert state.legs[0] == prefix_leg
    assert routes.calls == [("anchor", "fixed")] * 10


@pytest.mark.parametrize(
    ("arrive", "depart"), [(time(11, 30), time(12)), (time(13), time(13, 30)), (time(17, 30), time(18))]
)
def test_validate_boundary_times_are_allowed_and_never_calls_routes_or_mutates(arrive: time, depart: time) -> None:
    hours = OpeningHours(open_time=time(9), close_time=time(18), break_start=time(12), break_end=time(13))
    engine, _, routes = _engine(("a",), details_factory=lambda pid: _details(pid, hours=hours))
    state = ScheduleState(blocks=(_block("a", 10, arrive=arrive, depart=depart),))
    before = state.model_dump_json()
    report = engine.validate(ValidateInput(trip=_trip(), schedule=state))
    assert not report.violations
    assert not report.conflicts
    assert state.model_dump_json() == before
    assert routes.calls == []
