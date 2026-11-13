"""AC-006 시나리오: 실제 엔진 편집 결과에 EditHistory 스냅샷·판정을 적용한다."""

from datetime import date, time

from app.modules.engine.schemas import BlockDraft, FixedWindow, InsertInput, ScheduleState
from app.modules.trips.edit_history import EditHistory, InMemorySnapshotRepository, ac006_violations
from tests.unit.engine.test_service import _block, _engine, _public_ref, _trip

TRIP = "trip-1"


def _state() -> ScheduleState:
    return ScheduleState(
        blocks=(
            _block("a", 1, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 2, arrive=time(10), depart=time(10, 30)),
            _block("f", 3, arrive=time(15), depart=time(16), stay=60, fixed=True),
            _block("next-day", 1, arrive=time(9), depart=time(9, 30), fixed=True, day_no=2),
        )
    )


def test_anchor_insert_then_undo_satisfies_ac006() -> None:
    engine, _, _ = _engine(("a", "b", "f", "new", "next-day"))
    trip = _trip(end_date=date(2026, 11, 3))
    before = _state()
    history = EditHistory(InMemorySnapshotRepository())

    history.record_before_edit(TRIP, before)
    result = engine.insert(
        InsertInput(
            trip=trip,
            schedule=before,
            block=BlockDraft(place_ref=_public_ref("new"), is_fixed=False, stay_min=30, origin="USER"),
            from_block_id="a",
            to_block_id="b",
            block_id="new",
        )
    )

    assert [(b.id, b.seq) for b in result.state.blocks if b.day_no == 1] == [("a", 1), ("new", 2), ("b", 3), ("f", 4)]
    assert ac006_violations(before, result.state, day_no=1, anchor_seq=1) == set()
    assert history.undo(TRIP) == before


def test_day_append_then_undo_satisfies_ac006() -> None:
    engine, _, _ = _engine(("a", "b", "f", "new", "next-day"))
    trip = _trip(end_date=date(2026, 11, 3))
    before = _state()
    history = EditHistory(InMemorySnapshotRepository())

    history.record_before_edit(TRIP, before)
    result = engine.insert(
        InsertInput(
            trip=trip,
            schedule=before,
            block=BlockDraft(
                place_ref=_public_ref("new"),
                is_fixed=True,
                fixed_window=FixedWindow(day_no=1, start=time(17), end=time(17, 30)),
                stay_min=30,
                origin="USER",
            ),
            block_id="new",
        )
    )

    assert [(b.id, b.seq) for b in result.state.blocks if b.day_no == 1][-1] == ("new", 4)
    assert ac006_violations(before, result.state, day_no=1, anchor_seq=3) == set()
    assert history.undo(TRIP) == before
