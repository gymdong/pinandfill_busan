"""FR-006 / AC-006: 직전 편집 1단계 되돌리기(Memento)와 편집 범위 판정."""

from datetime import time

import pytest

from app.modules.engine.schemas import PublicPlaceRef, ScheduleState, StoredBlock, StoredLeg
from app.modules.trips.edit_history import (
    EditHistory,
    InMemorySnapshotRepository,
    NothingToUndoError,
    SnapshotReason,
    ac006_violations,
    changed_block_ids,
)

TRIP = "trip-1"


def block(block_id: str, seq: int, *, day: int = 1, stay: int = 30, fixed: bool = False, at: int | None = None):
    arrive = time(at, 0) if at is not None else None
    depart = time(at, stay) if at is not None else None
    return StoredBlock(
        id=block_id,
        day_no=day,
        seq=seq,
        place_ref=PublicPlaceRef(place_id=f"p-{block_id}"),
        is_fixed=fixed,
        fixed_start=arrive if fixed else None,
        fixed_end=depart if fixed else None,
        stay_min=stay,
        arrive_at=arrive,
        depart_at=depart,
        origin="USER",
    )


def state(*blocks: StoredBlock, legs: tuple[StoredLeg, ...] = ()) -> ScheduleState:
    return ScheduleState(blocks=blocks, legs=legs)


@pytest.fixture
def history() -> EditHistory:
    return EditHistory(InMemorySnapshotRepository())


# ---- 되돌리기 ----


def test_undo_restores_state_before_last_edit(history):
    leg = StoredLeg(id="l1", from_block_id="a", to_block_id="b", mode="WALK", duration_min=5, source="ESTIMATED")
    before = state(block("a", 1, at=9), block("b", 2, at=10), legs=(leg,))
    history.record_before_edit(TRIP, before)
    assert history.undo(TRIP) == before


def test_only_one_step_can_be_undone(history):
    history.record_before_edit(TRIP, state(block("a", 1)))
    history.undo(TRIP)
    with pytest.raises(NothingToUndoError):
        history.undo(TRIP)


def test_new_edit_replaces_previous_snapshot(history):
    history.record_before_edit(TRIP, state(block("a", 1)))
    second = state(block("a", 1), block("b", 2))
    history.record_before_edit(TRIP, second)
    assert history.undo(TRIP) == second
    with pytest.raises(NothingToUndoError):
        history.undo(TRIP)


def test_undo_without_edit_raises(history):
    with pytest.raises(NothingToUndoError):
        history.undo(TRIP)


def test_trips_are_isolated(history):
    history.record_before_edit("a", state(block("a", 1)))
    with pytest.raises(NothingToUndoError):
        history.undo("b")


def test_snapshot_payload_is_plain_json_without_aliases_loss(history):
    snapshot = history.record_before_edit(TRIP, state(block("a", 1, at=9)))
    # schedule_snapshots.payload(JSONB)에 그대로 들어갈 수 있는 값이어야 한다.
    stored = snapshot.payload["blocks"][0]
    assert stored["arriveAt"] == "09:00"
    assert stored["placeRef"] == {"kind": "PUBLIC", "placeId": "p-a"}


def test_undo_ignores_non_edit_snapshots(history):
    repo = history.repository
    history.record(TRIP, state(block("a", 1)), SnapshotReason.PLAN_B)
    with pytest.raises(NothingToUndoError):
        history.undo(TRIP)
    assert repo.latest(TRIP, SnapshotReason.PLAN_B) is not None


def test_version_increases_per_trip(history):
    history.record_before_edit(TRIP, state(block("a", 1)))
    history.record_before_edit(TRIP, state(block("a", 1, stay=40)))
    assert history.repository.latest(TRIP, SnapshotReason.EDIT).version == 2


# ---- 변경 블록 ----


def test_changed_block_ids_reports_added_removed_and_modified():
    before = state(block("a", 1), block("b", 2), block("c", 3))
    after = state(block("a", 1), block("b", 2, stay=60), block("d", 3))
    assert changed_block_ids(before, after) == {"b", "c", "d"}


def test_changed_block_ids_detects_day_move():
    assert changed_block_ids(state(block("a", 1, day=1)), state(block("a", 1, day=2))) == {"a"}


# ---- AC-006 판정 (PR #11 합의: 같은 날 seq 1..n) ----


def test_insert_after_anchor_shifts_only_later_seq():
    before = state(block("a", 1, at=9), block("b", 2, at=10), block("c", 3, day=2, at=9))
    after = state(block("a", 1, at=9), block("n", 2), block("b", 3, at=11), block("c", 3, day=2, at=9))
    assert ac006_violations(before, after, day_no=1, anchor_seq=1) == set()


def test_prefix_change_is_a_violation_even_if_only_seq():
    before = state(block("a", 1), block("b", 2))
    after = state(block("a", 10), block("b", 20))
    assert ac006_violations(before, after, day_no=1, anchor_seq=1) == {"a"}


def test_other_day_change_is_a_violation():
    before = state(block("a", 1), block("c", 1, day=2, at=9))
    after = state(block("a", 1), block("c", 1, day=2, at=10))
    assert ac006_violations(before, after, day_no=1, anchor_seq=1) == {"c"}


def test_later_fixed_block_may_move_position_but_not_time():
    before = state(block("a", 1, at=9), block("f", 2, fixed=True, at=15))
    moved = state(block("a", 1, at=9), block("n", 2), block("f", 3, fixed=True, at=15))
    assert ac006_violations(before, moved, day_no=1, anchor_seq=1) == set()
    shifted = state(block("a", 1, at=9), block("n", 2), block("f", 3, fixed=True, at=16))
    assert ac006_violations(before, shifted, day_no=1, anchor_seq=1) == {"f"}


def test_later_flexible_blocks_may_be_recomputed():
    before = state(block("a", 1, at=9), block("b", 2, at=10))
    after = state(block("a", 1, at=9), block("b", 2, at=11))
    assert ac006_violations(before, after, day_no=1, anchor_seq=1) == set()


def test_edited_block_itself_is_excluded():
    before = state(block("a", 1, at=9), block("f", 2, fixed=True, at=15))
    deleted = state(block("a", 1, at=9))
    assert ac006_violations(before, deleted, day_no=1, anchor_seq=1, edited_block_id="f") == set()
    assert ac006_violations(before, deleted, day_no=1, anchor_seq=1) == {"f"}


def test_first_block_on_empty_day_has_no_prefix():
    before = state(block("c", 1, day=2, at=9))
    after = state(block("n", 1), block("c", 1, day=2, at=9))
    assert ac006_violations(before, after, day_no=1, anchor_seq=0) == set()
