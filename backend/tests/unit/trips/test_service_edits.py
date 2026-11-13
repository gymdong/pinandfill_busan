"""FR-006: API-007(편집)·008(삭제)·010(되돌리기)의 TripService 동작과 편집 유형별 AC-006 판정."""

from datetime import date, time

import pytest

from app.modules.engine.schemas import RecomputeInput, ScheduleState
from app.modules.engine.service import (
    EngineInputError,
    NeedsConfirmationError,
    SequenceNormalizationRequiredError,
)
from app.modules.trips.commands import FixedWindowRequiredError
from app.modules.trips.edit_history import NothingToUndoError, ac006_violations
from app.modules.trips.repository import FakeTripRepository, TripRecord
from app.modules.trips.schemas import (
    AddBlockRequest,
    DeleteBlockRequest,
    GenerateScheduleRequest,
    PublicPlaceInput,
    UndoRequest,
    UpdateBlockRequest,
)
from app.modules.trips.service import FixedScheduleConflictError, TripService
from tests.unit.engine.test_service import _block, _engine, _trip

TRIP = "trip"
PLACES = ("a", "b", "c", "f", "g", "d", "e", "h", "new")


def setup_service():
    """1일차: a(고정 09:00) b c f(고정 15:00~16:00) g, 2일차: d(일반 09:00) e, 3일차: h 하나. 이동 15분."""
    engine, _, routes = _engine(PLACES)
    trip = _trip(end_date=date(2026, 11, 4))
    state = ScheduleState(
        blocks=(
            _block("a", 1, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 2, arrive=None, depart=None),
            _block("c", 3, arrive=None, depart=None),
            _block("f", 4, arrive=time(15), depart=time(16), stay=60, fixed=True),
            _block("g", 5, arrive=None, depart=None),
            _block("d", 1, arrive=time(9), depart=time(9, 30), day_no=2),
            _block("e", 2, arrive=None, depart=None, day_no=2),
            _block("h", 1, arrive=time(10), depart=time(10, 30), day_no=3),
        )
    )
    for anchor in ("a", "d"):
        state = engine.recompute(RecomputeInput(trip=trip, schedule=state, from_block_id=anchor)).state
    repository = FakeTripRepository({TRIP: TripRecord(trip, state)})
    service = TripService(repository, engine, lambda place: 30)
    return service, repository, routes


def saved(repository: FakeTripRepository) -> ScheduleState:
    record = repository.get(TRIP)
    assert record is not None
    return record.schedule


def times(state: ScheduleState, block_id: str) -> tuple[time | None, time | None]:
    block = next(b for b in state.blocks if b.id == block_id)
    return block.arrive_at, block.depart_at


def order(state: ScheduleState, day_no: int) -> list[tuple[str, int]]:
    return [(b.id, b.seq) for b in state.blocks if b.day_no == day_no]


def leg_pairs(state: ScheduleState) -> set[tuple[str, str]]:
    return {(leg.from_block_id, leg.to_block_id) for leg in state.legs}


def stay(minutes: int) -> UpdateBlockRequest:
    return UpdateBlockRequest(stay_min=minutes)


def test_fixture_is_consistent_before_edits():
    _, repository, _ = setup_service()
    before = saved(repository)
    assert times(before, "b") == (time(9, 45), time(10, 15))
    assert times(before, "c") == (time(10, 30), time(11))
    assert times(before, "g") == (time(16, 15), time(16, 45))
    assert times(before, "e") == (time(9, 45), time(10, 15))


# ---- stayMin ----


def test_stay_change_recomputes_block_and_later_then_undo_restores():
    service, repository, _ = setup_service()
    before = saved(repository)

    response = service.update_block(TRIP, "b", stay(60))

    after = saved(repository)
    assert times(after, "b") == (time(9, 45), time(10, 45))
    assert times(after, "c") == (time(11), time(11, 30))
    assert times(after, "f") == times(before, "f")
    assert ac006_violations(before, after, day_no=1, anchor_seq=1, edited_block_id="b") == set()
    assert response.schedule.days[0].blocks[1].depart_at == time(10, 45)
    assert response.violations == response.schedule.violations

    undone = service.undo(TRIP, UndoRequest())
    assert saved(repository) == before
    assert undone.schedule.days[0].blocks[1].depart_at == time(10, 15)


def test_first_block_stay_change_moves_its_departure():
    service, repository, _ = setup_service()
    before = saved(repository)

    service.update_block(TRIP, "d", stay(60))

    after = saved(repository)
    assert times(after, "d") == (time(9), time(10))
    assert times(after, "e") == (time(10, 15), time(10, 45))
    assert ac006_violations(before, after, day_no=2, anchor_seq=0, edited_block_id="d") == set()


# ---- seq ----


@pytest.mark.parametrize(("block_id", "seq"), [("c", 2), ("b", 3)])
def test_move_renumbers_densely_and_recomputes_from_min_position(block_id, seq):
    service, repository, _ = setup_service()
    before = saved(repository)
    unchanged_leg = next(leg for leg in before.legs if (leg.from_block_id, leg.to_block_id) == ("f", "g"))

    service.update_block(TRIP, block_id, UpdateBlockRequest(seq=seq))

    after = saved(repository)
    assert order(after, 1) == [("a", 1), ("c", 2), ("b", 3), ("f", 4), ("g", 5)]
    assert times(after, "c") == (time(9, 45), time(10, 15))
    assert times(after, "b") == (time(10, 30), time(11))
    assert leg_pairs(after) >= {("a", "c"), ("c", "b"), ("b", "f")}
    assert not leg_pairs(after) & {("a", "b"), ("b", "c"), ("c", "f")}
    assert unchanged_leg in after.legs
    assert ac006_violations(before, after, day_no=1, anchor_seq=1, edited_block_id=block_id) == set()


def test_move_to_first_position_takes_over_day_start():
    service, repository, _ = setup_service()
    before = saved(repository)

    service.update_block(TRIP, "e", UpdateBlockRequest(seq=1))

    after = saved(repository)
    assert order(after, 2) == [("e", 1), ("d", 2)]
    assert times(after, "e") == (time(9), time(9, 30))
    assert times(after, "d") == (time(9, 45), time(10, 15))
    assert ac006_violations(before, after, day_no=2, anchor_seq=0, edited_block_id="e") == set()


def test_move_that_breaks_a_fixed_time_is_rejected_without_saving():
    service, repository, _ = setup_service()
    before = saved(repository)

    with pytest.raises(FixedScheduleConflictError):
        service.update_block(TRIP, "b", UpdateBlockRequest(seq=1))

    assert saved(repository) == before


# ---- isFixed ----


def test_release_fixed_keeps_times_clears_window_and_recomputes_later():
    service, repository, _ = setup_service()
    before = saved(repository)

    service.update_block(TRIP, "f", UpdateBlockRequest(is_fixed=False))

    after = saved(repository)
    released = next(b for b in after.blocks if b.id == "f")
    assert (released.is_fixed, released.fixed_start, released.fixed_end) == (False, None, None)
    assert times(after, "f") == (time(15), time(16))
    assert times(after, "g") == (time(16, 15), time(16, 45))
    assert ac006_violations(before, after, day_no=1, anchor_seq=3, edited_block_id="f") == set()


def test_fixing_without_designated_window_is_rejected_and_not_recorded():
    service, repository, _ = setup_service()
    before = saved(repository)

    with pytest.raises(FixedWindowRequiredError):
        service.update_block(TRIP, "b", UpdateBlockRequest(is_fixed=True))

    assert saved(repository) == before
    with pytest.raises(NothingToUndoError):
        service.undo(TRIP, UndoRequest())


def test_fixing_with_kept_window_uses_that_window():
    service, repository, _ = setup_service()
    state = saved(repository)
    blocks = tuple(
        b.model_copy(update={"fixed_start": time(9, 45), "fixed_end": time(10, 15)}) if b.id == "b" else b
        for b in state.blocks
    )
    repository.save(TRIP, TripRecord(repository.get(TRIP).trip, ScheduleState(blocks=blocks, legs=state.legs)))
    before = saved(repository)

    service.update_block(TRIP, "b", UpdateBlockRequest(is_fixed=True))

    after = saved(repository)
    assert next(b for b in after.blocks if b.id == "b").is_fixed
    assert times(after, "b") == (time(9, 45), time(10, 15))
    assert ac006_violations(before, after, day_no=1, anchor_seq=1, edited_block_id="b") == set()


@pytest.mark.parametrize(
    ("block_id", "request_body"),
    [
        ("b", UpdateBlockRequest(stay_min=30)),
        ("b", UpdateBlockRequest(seq=2)),
        ("a", UpdateBlockRequest(is_fixed=True)),
    ],
)
def test_unchanged_edit_is_neither_saved_nor_recorded(block_id, request_body):
    service, repository, routes = setup_service()
    before = saved(repository)
    calls = len(routes.calls)

    response = service.update_block(TRIP, block_id, request_body)

    assert saved(repository) == before
    assert len(routes.calls) == calls
    assert [b.id for b in response.schedule.days[0].blocks] == ["a", "b", "c", "f", "g"]
    with pytest.raises(NothingToUndoError):
        service.undo(TRIP, UndoRequest())


# ---- delete ----


def test_delete_pulls_later_blocks_and_recomputes_from_previous():
    service, repository, _ = setup_service()
    before = saved(repository)

    response = service.delete_block(TRIP, "b", DeleteBlockRequest())

    after = saved(repository)
    assert order(after, 1) == [("a", 1), ("c", 2), ("f", 3), ("g", 4)]
    assert times(after, "c") == (time(9, 45), time(10, 15))
    assert not any("b" in pair for pair in leg_pairs(after))
    assert ("a", "c") in leg_pairs(after)
    assert ac006_violations(before, after, day_no=1, anchor_seq=1, edited_block_id="b") == set()
    assert [b.id for b in response.schedule.days[0].blocks] == ["a", "c", "f", "g"]

    service.undo(TRIP, UndoRequest())
    assert saved(repository) == before


def test_delete_first_block_hands_day_start_to_next_block():
    service, repository, _ = setup_service()
    before = saved(repository)

    service.delete_block(TRIP, "d", DeleteBlockRequest())

    after = saved(repository)
    assert order(after, 2) == [("e", 1)]
    assert times(after, "e") == (time(9), time(9, 30))
    assert not any("d" in pair for pair in leg_pairs(after))
    assert ac006_violations(before, after, day_no=2, anchor_seq=0, edited_block_id="d") == set()


def test_delete_first_fixed_block_keeps_next_fixed_time():
    service, repository, _ = setup_service()
    before = saved(repository)
    service.delete_block(TRIP, "b", DeleteBlockRequest())
    service.delete_block(TRIP, "c", DeleteBlockRequest())
    service.delete_block(TRIP, "a", DeleteBlockRequest())

    after = saved(repository)
    assert order(after, 1) == [("f", 1), ("g", 2)]
    assert times(after, "f") == times(before, "f")
    assert times(after, "g") == times(before, "g")


def test_delete_only_block_of_day_projects_without_route_lookups():
    service, repository, routes = setup_service()
    before = saved(repository)
    calls = len(routes.calls)

    response = service.delete_block(TRIP, "h", DeleteBlockRequest())

    after = saved(repository)
    assert order(after, 3) == []
    assert len(routes.calls) == calls
    assert response.schedule.days[2].blocks == ()
    assert ac006_violations(before, after, day_no=3, anchor_seq=0, edited_block_id="h") == set()
    service.undo(TRIP, UndoRequest())
    assert saved(repository) == before


# ---- 입력 오류 ----


@pytest.mark.parametrize(
    "edit",
    [
        lambda s: s.update_block(TRIP, "missing", stay(40)),
        lambda s: s.update_block(TRIP, "b", UpdateBlockRequest(seq=6)),
        lambda s: s.update_block(TRIP, "e", UpdateBlockRequest(seq=3)),
        lambda s: s.delete_block(TRIP, "missing", DeleteBlockRequest()),
    ],
)
def test_unknown_block_or_out_of_day_seq_is_rejected(edit):
    service, repository, _ = setup_service()
    before = saved(repository)
    with pytest.raises(EngineInputError):
        edit(service)
    assert saved(repository) == before


@pytest.mark.parametrize(
    "edit",
    [
        lambda s: s.update_block(TRIP, "b", stay(40)),
        lambda s: s.delete_block(TRIP, "b", DeleteBlockRequest()),
    ],
)
def test_legacy_sequences_require_explicit_normalization(edit):
    service, repository, _ = setup_service()
    record = repository.get(TRIP)
    legacy = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 20, arrive=time(9, 45), depart=time(10, 15)),
        )
    )
    repository.save(TRIP, TripRecord(record.trip, legacy))
    with pytest.raises(SequenceNormalizationRequiredError):
        edit(service)
    assert saved(repository) == legacy


# ---- 스냅샷 순서 ----


def _route_failure(service: TripService, routes) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("route provider down")

    routes.estimate = fail
    service.update_block(TRIP, "c", stay(45))


@pytest.mark.parametrize(
    ("failing_edit", "error"),
    [
        (lambda s, r: s.update_block(TRIP, "missing", stay(45)), EngineInputError),
        (lambda s, r: s.update_block(TRIP, "b", UpdateBlockRequest(seq=9)), EngineInputError),
        (_route_failure, RuntimeError),
        (lambda s, r: s.update_block(TRIP, "a", stay(60)), FixedScheduleConflictError),
        (lambda s, r: s.update_block(TRIP, "b", UpdateBlockRequest(is_fixed=True)), FixedWindowRequiredError),
    ],
)
def test_rejected_edit_keeps_previous_snapshot(failing_edit, error):
    service, repository, routes = setup_service()
    before = saved(repository)
    service.update_block(TRIP, "b", stay(60))
    after_first = saved(repository)

    with pytest.raises(error):
        failing_edit(service, routes)

    assert saved(repository) == after_first
    service.undo(TRIP, UndoRequest())
    assert saved(repository) == before


def test_insert_is_an_undoable_edit():
    service, repository, _ = setup_service()
    before = saved(repository)
    request = AddBlockRequest(
        place=PublicPlaceInput(place_id="new"), is_fixed=False, origin="USER", from_block_id="a", to_block_id="b"
    )

    service.insert(TRIP, request)
    assert len(saved(repository).blocks) == len(before.blocks) + 1

    service.undo(TRIP, UndoRequest())
    assert saved(repository) == before


def test_generate_is_not_recorded():
    service, repository, _ = setup_service()
    service.generate(TRIP, GenerateScheduleRequest())
    with pytest.raises(NothingToUndoError):
        service.undo(TRIP, UndoRequest())


def test_undo_is_one_step_and_does_not_record_itself():
    service, repository, routes = setup_service()
    service.update_block(TRIP, "b", stay(60))
    after_first = saved(repository)
    service.delete_block(TRIP, "c", DeleteBlockRequest())
    calls = len(routes.calls)

    service.undo(TRIP, UndoRequest())

    assert saved(repository) == after_first
    assert len(routes.calls) == calls
    with pytest.raises(NothingToUndoError):
        service.undo(TRIP, UndoRequest())


def test_undo_projection_failure_restores_snapshot_and_state(monkeypatch):
    service, repository, _ = setup_service()
    before = saved(repository)
    service.update_block(TRIP, "b", stay(60))
    after_first = saved(repository)

    def fail(*args, **kwargs):
        raise NeedsConfirmationError("display data unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(service.engine, "project", fail)
        with pytest.raises(NeedsConfirmationError):
            service.undo(TRIP, UndoRequest())
    assert saved(repository) == after_first

    service.undo(TRIP, UndoRequest())
    assert saved(repository) == before
