"""블록 편집 되돌리기(Memento, SDD 6장 EditHistory / ScheduleSnapshot).

편집 직전의 일정 전체를 스냅샷으로 저장하고 직전 1단계만 복원한다(FR-006, AC-006).
저장소는 `SnapshotRepository` 로 추상화해 DB(schedule_snapshots)와 시험용 메모리 구현을 바꿔 끼운다(NFR-009).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

Payload = dict[str, Any]


class SnapshotReason(StrEnum):
    """schedule_snapshots.reason"""

    GENERATE = "GENERATE"
    EDIT = "EDIT"
    PLAN_B = "PLAN_B"


class NothingToUndoError(Exception):
    """되돌릴 직전 편집이 없다. API-010 은 409 로 변환한다."""


@dataclass(frozen=True)
class ScheduleSnapshot:
    trip_id: str
    version: int
    payload: Payload  # 변경 전 일정(블록·구간) 전체
    reason: SnapshotReason
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class SnapshotRepository(Protocol):
    def next_version(self, trip_id: str) -> int: ...

    def save(self, snapshot: ScheduleSnapshot) -> None: ...

    def latest(self, trip_id: str, reason: SnapshotReason) -> ScheduleSnapshot | None: ...

    def delete(self, snapshot: ScheduleSnapshot) -> None: ...


class InMemorySnapshotRepository:
    def __init__(self) -> None:
        self._items: list[ScheduleSnapshot] = []

    def next_version(self, trip_id: str) -> int:
        return max((s.version for s in self._items if s.trip_id == trip_id), default=0) + 1

    def save(self, snapshot: ScheduleSnapshot) -> None:
        self._items.append(snapshot)

    def latest(self, trip_id: str, reason: SnapshotReason) -> ScheduleSnapshot | None:
        matches = [s for s in self._items if s.trip_id == trip_id and s.reason == reason]
        return max(matches, key=lambda s: s.version, default=None)

    def delete(self, snapshot: ScheduleSnapshot) -> None:
        self._items.remove(snapshot)


class EditHistory:
    def __init__(self, repository: SnapshotRepository) -> None:
        self.repository = repository

    def record(self, trip_id: str, payload: Payload, reason: SnapshotReason) -> ScheduleSnapshot:
        snapshot = ScheduleSnapshot(
            trip_id=trip_id,
            version=self.repository.next_version(trip_id),
            payload=copy.deepcopy(payload),
            reason=reason,
        )
        if reason is SnapshotReason.EDIT:
            # 1단계만 되돌리므로 이전 EDIT 스냅샷은 새 편집이 대체한다.
            previous = self.repository.latest(trip_id, SnapshotReason.EDIT)
            if previous:
                self.repository.delete(previous)
        self.repository.save(snapshot)
        return snapshot

    def record_before_edit(self, trip_id: str, payload: Payload) -> ScheduleSnapshot:
        """편집을 적용하기 전에 호출한다."""
        return self.record(trip_id, payload, SnapshotReason.EDIT)

    def undo(self, trip_id: str) -> Payload:
        """직전 EDIT 스냅샷을 소비해 돌려준다. 호출자가 이 일정으로 blocks·legs 를 복원한다."""
        snapshot = self.repository.latest(trip_id, SnapshotReason.EDIT)
        if snapshot is None:
            raise NothingToUndoError(trip_id)
        self.repository.delete(snapshot)
        return copy.deepcopy(snapshot.payload)


def changed_block_ids(before: Payload, after: Payload) -> set[str]:
    """두 일정 사이에 추가·삭제·변경된 블록 id. AC-006(변경 블록 뒤 외 변경률 0%) 검사에 쓴다."""

    def blocks(schedule: Payload) -> dict[str, Any]:
        return {b["id"]: b for day in schedule.get("days", []) for b in day.get("blocks", [])}

    old, new = blocks(before), blocks(after)
    return {i for i in old.keys() | new.keys() if old.get(i) != new.get(i)}
