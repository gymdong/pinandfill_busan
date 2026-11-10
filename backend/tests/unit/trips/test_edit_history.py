"""FR-006 / AC-006: 직전 편집 1단계 되돌리기(Memento)."""

import pytest

from app.modules.trips.edit_history import (
    EditHistory,
    InMemorySnapshotRepository,
    NothingToUndoError,
    SnapshotReason,
    changed_block_ids,
)

TRIP = "trip-1"


def schedule(*stays: int) -> dict:
    return {"days": [{"blocks": [{"id": f"b{i}", "seq": i, "stayMin": s} for i, s in enumerate(stays, 1)]}]}


@pytest.fixture
def history() -> EditHistory:
    return EditHistory(InMemorySnapshotRepository())


def test_undo_restores_schedule_before_last_edit(history):
    before = schedule(30, 60)
    history.record_before_edit(TRIP, before)
    assert history.undo(TRIP) == before


def test_only_one_step_can_be_undone(history):
    history.record_before_edit(TRIP, schedule(30))
    history.undo(TRIP)
    with pytest.raises(NothingToUndoError):
        history.undo(TRIP)


def test_new_edit_replaces_previous_snapshot(history):
    history.record_before_edit(TRIP, schedule(30))
    second = schedule(45)
    history.record_before_edit(TRIP, second)
    assert history.undo(TRIP) == second
    with pytest.raises(NothingToUndoError):
        history.undo(TRIP)


def test_undo_without_edit_raises(history):
    with pytest.raises(NothingToUndoError):
        history.undo(TRIP)


def test_trips_are_isolated(history):
    history.record_before_edit("a", schedule(30))
    with pytest.raises(NothingToUndoError):
        history.undo("b")


def test_snapshot_is_a_deep_copy(history):
    payload = schedule(30)
    history.record_before_edit(TRIP, payload)
    payload["days"][0]["blocks"][0]["stayMin"] = 999
    assert history.undo(TRIP)["days"][0]["blocks"][0]["stayMin"] == 30


def test_undo_ignores_non_edit_snapshots(history):
    repo = history.repository
    history.record(TRIP, schedule(30), SnapshotReason.PLAN_B)
    assert repo.latest(TRIP, SnapshotReason.PLAN_B) is not None
    with pytest.raises(NothingToUndoError):
        history.undo(TRIP)
    assert repo.latest(TRIP, SnapshotReason.PLAN_B) is not None


def test_version_increases_per_trip(history):
    history.record_before_edit(TRIP, schedule(30))
    history.record_before_edit(TRIP, schedule(40))
    assert history.repository.latest(TRIP, SnapshotReason.EDIT).version == 2


def test_changed_block_ids_reports_only_differences():
    before = schedule(30, 60, 20)
    after = schedule(30, 90, 20)
    assert changed_block_ids(before, after) == {"b2"}


def test_changed_block_ids_counts_added_and_removed():
    assert changed_block_ids(schedule(30, 60), schedule(30)) == {"b2"}
    assert changed_block_ids(schedule(30), schedule(30, 60)) == {"b2"}
