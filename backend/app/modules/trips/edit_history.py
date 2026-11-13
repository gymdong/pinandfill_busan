"""블록 편집 되돌리기(Memento, SDD 6장 EditHistory / ScheduleSnapshot).

편집 직전의 엔진 상태(`ScheduleState`)를 스냅샷으로 저장하고 직전 1단계만 복원한다(FR-006, AC-006).
`ScheduleState`는 장소 참조(ID·URL)만 담으므로 카카오 이름·좌표가 스냅샷에 들어가지 않는다(D6).

저장소는 `SnapshotRepository` 로 추상화한다(NFR-009). `InMemorySnapshotRepository` 는 시험용이며
프로세스가 재시작되면 이력이 사라진다. 운영에서는 schedule_snapshots 테이블 구현을 주입한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from app.modules.engine.schemas import ScheduleState, StoredBlock

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
    payload: Payload  # 변경 전 일정(블록·구간) 전체. schedule_snapshots.payload(JSONB)
    reason: SnapshotReason
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class SnapshotRepository(Protocol):
    """DB 구현은 다음을 지켜야 한다.

    - `EditHistory.record` 의 이전 EDIT 삭제와 새 스냅샷 저장은 같은 트랜잭션이어야 한다.
    - `EditHistory.undo` 의 스냅샷 삭제는 blocks·legs 복원과 같은 트랜잭션이어야 한다.
      그렇지 않으면 복원에 실패했을 때 되돌릴 이력이 사라진다.
    """

    def next_version(self, trip_id: str) -> int: ...

    def save(self, snapshot: ScheduleSnapshot) -> None: ...

    def latest(self, trip_id: str, reason: SnapshotReason) -> ScheduleSnapshot | None: ...

    def delete(self, snapshot: ScheduleSnapshot) -> None: ...


class InMemorySnapshotRepository:
    """시험용. 운영 경로에 주입하지 않는다."""

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

    def record(self, trip_id: str, state: ScheduleState, reason: SnapshotReason) -> ScheduleSnapshot:
        snapshot = ScheduleSnapshot(
            trip_id=trip_id,
            version=self.repository.next_version(trip_id),
            payload=state.model_dump(mode="json", by_alias=True),
            reason=reason,
        )
        if reason is SnapshotReason.EDIT:
            # 1단계만 되돌리므로 이전 EDIT 스냅샷은 새 편집이 대체한다.
            previous = self.repository.latest(trip_id, SnapshotReason.EDIT)
            if previous:
                self.repository.delete(previous)
        self.repository.save(snapshot)
        return snapshot

    def record_before_edit(self, trip_id: str, state: ScheduleState) -> ScheduleSnapshot:
        """편집을 적용하기 전의 상태로 호출한다."""
        return self.record(trip_id, state, SnapshotReason.EDIT)

    def latest_edit(self, trip_id: str) -> ScheduleSnapshot | None:
        """지금 되돌릴 수 있는 EDIT 스냅샷. 저장 실패 시 `restore` 로 이 상태를 되살리려고 먼저 받아 둔다."""
        return self.repository.latest(trip_id, SnapshotReason.EDIT)

    def restore(self, trip_id: str, snapshot: ScheduleSnapshot | None) -> None:
        """되돌리기 지점을 `latest_edit` 로 받아 둔 상태로 정확히 되돌린다(None 이면 없앤다).

        일정 저장이 실패했을 때의 보상 동작이다. DB 구현에서는 같은 트랜잭션의 롤백이 대신한다.
        """
        current = self.repository.latest(trip_id, SnapshotReason.EDIT)
        if current is not None:
            self.repository.delete(current)
        if snapshot is not None:
            self.repository.save(snapshot)

    def discard(self, trip_id: str) -> None:
        """되돌리기 지점을 없앤다(없으면 아무것도 하지 않는다). 일정 생성(API-009)이 일정을 바꾼 뒤에 부른다."""
        self.restore(trip_id, None)

    def undo(self, trip_id: str) -> ScheduleState:
        """직전 EDIT 스냅샷을 소비해 그 상태를 돌려준다. 호출자가 이 상태로 저장한다."""
        snapshot = self.repository.latest(trip_id, SnapshotReason.EDIT)
        if snapshot is None:
            raise NothingToUndoError(trip_id)
        self.repository.delete(snapshot)
        return ScheduleState.model_validate(snapshot.payload)


def _blocks(state: ScheduleState) -> dict[str, StoredBlock]:
    return {b.id: b for b in state.blocks}


def changed_block_ids(before: ScheduleState, after: ScheduleState) -> set[str]:
    """두 상태 사이에 추가·삭제·변경된 블록 id(일차 이동 포함)."""
    old, new = _blocks(before), _blocks(after)
    return {i for i in old.keys() | new.keys() if old.get(i) != new.get(i)}


def ac006_violations(
    before: ScheduleState,
    after: ScheduleState,
    *,
    day_no: int,
    anchor_seq: int,
    edited_block_id: str | None = None,
) -> set[str]:
    """AC-006 위반 블록 id. 규칙은 PR #11에서 합의한 같은 날 seq 1..n 기준이다.

    - 다른 날 블록과, 편집한 날의 재계산 시작점(`anchor_seq`) 이하 블록은 seq 를 포함해 그대로여야 한다.
    - 시작점 뒤의 고정 블록은 seq(위치)만 바뀔 수 있고 지정 시각·도착·출발 시각은 그대로여야 한다.
    - 시작점 뒤의 일반 블록은 재계산 대상이다.
    - 편집한 블록 자체(`edited_block_id`, 예: 삭제·순서 변경 대상)는 판정에서 뺀다.

    빈 날의 첫 블록 추가처럼 앞쪽 블록이 없으면 `anchor_seq=0` 으로 부른다.
    """
    new = _blocks(after)
    violations: set[str] = set()
    for old in before.blocks:
        if old.id == edited_block_id:
            continue
        current = new.get(old.id)
        if old.day_no != day_no or old.seq <= anchor_seq:
            if current != old:
                violations.add(old.id)
        elif old.is_fixed:
            if current is None or current.model_copy(update={"seq": old.seq}) != old:
                violations.add(old.id)
    return violations
