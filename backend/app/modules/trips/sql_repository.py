"""`TripRepository`·`SnapshotRepository` 의 DB 구현(trips·blocks·legs·schedule_snapshots).

- 서비스가 편집 한 번을 `Database.transaction()` 으로 감싸면 일정 저장과 스냅샷 기록이 한 트랜잭션이다.
  실패하면 함께 롤백되므로 `EditHistory` 의 보상 동작(`restore`)이 남긴 쓰기도 커밋되지 않는다.
- 쓰기는 SAVEPOINT 안에서 한다. 쓰기가 DB 오류로 실패해도 세션이 계속 쓸 수 있는 상태로 남아,
  서비스의 보상 코드가 원래 예외를 가리지 않는다.
- 트랜잭션 안의 `get` 은 trips 행을 잠근다(SELECT ... FOR UPDATE). 워커가 여러 개여도 한 여행의
  읽기-계산-저장이 직렬화된다. 서비스의 RLock 은 같은 프로세스 안에서만 유효하다.
- 장소 참조(공공 장소 ID, 카카오 ID·URL)만 저장한다. 카카오 장소명·좌표는 도메인 상태에 없으므로 저장되지 않는다.
  근거: SDD 출처 구분 USER_SELECTED("일정에 필요한 최소 필드만 저장", D6). 카카오 응답 본문은 저장하지 않는다.
  D6(카카오 문의) 결과 ID·URL 도 저장할 수 없게 되면 이 두 열과 메모리 저장소를 함께 바꾼다.
- 여행 ID 는 UUID 다. UUID 가 아닌 ID 는 없는 여행으로 본다.
"""

import uuid

from sqlalchemy import delete, func, insert, select

from app.db.models import BlockRow, LegRow, ScheduleSnapshotRow, TripRow
from app.db.session import Database
from app.modules.engine.schemas import KakaoPlaceRef, PublicPlaceRef, ScheduleState, StoredBlock, StoredLeg, TripWindow
from app.modules.trips.edit_history import ScheduleSnapshot, SnapshotReason
from app.modules.trips.repository import TripRecord


def _trip_key(trip_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(trip_id)
    except ValueError:
        return None


def _required_key(trip_id: str) -> uuid.UUID:
    key = _trip_key(trip_id)
    if key is None:
        raise ValueError("trip id must be a UUID")
    return key


def _block_values(key: uuid.UUID, position: int, block: StoredBlock) -> dict[str, object]:
    ref = block.place_ref
    return {
        "trip_id": key,
        "id": block.id,
        "position": position,
        "day_no": block.day_no,
        "seq": block.seq,
        "place_kind": ref.kind,
        "place_id": ref.place_id if isinstance(ref, PublicPlaceRef) else None,
        "kakao_place_id": ref.kakao_place_id if isinstance(ref, KakaoPlaceRef) else None,
        "kakao_place_url": str(ref.kakao_place_url) if isinstance(ref, KakaoPlaceRef) else None,
        "is_fixed": block.is_fixed,
        "fixed_start": block.fixed_start,
        "fixed_end": block.fixed_end,
        "stay_min": block.stay_min,
        "arrive_at": block.arrive_at,
        "depart_at": block.depart_at,
        "origin": block.origin,
    }


def _leg_values(key: uuid.UUID, position: int, leg: StoredLeg) -> dict[str, object]:
    return {"trip_id": key, "position": position, **leg.model_dump()}


def _block(row: BlockRow) -> StoredBlock:
    ref: dict[str, object]
    if row.place_kind == "KAKAO":
        ref = {"kind": "KAKAO", "kakao_place_id": row.kakao_place_id, "kakao_place_url": row.kakao_place_url}
    else:
        ref = {"kind": "PUBLIC", "place_id": row.place_id}
    fields = set(StoredBlock.model_fields) - {"place_ref"}
    return StoredBlock.model_validate({"place_ref": ref, **{name: getattr(row, name) for name in fields}})


def _leg(row: LegRow) -> StoredLeg:
    return StoredLeg.model_validate({name: getattr(row, name) for name in StoredLeg.model_fields})


class SqlTripRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, trip_id: str) -> TripRecord | None:
        key = _trip_key(trip_id)
        if key is None:
            return None
        lock = self.database.in_transaction()
        with self.database.transaction() as session:
            trip = session.get(TripRow, key, with_for_update=True if lock else None, populate_existing=True)
            if trip is None:
                return None
            blocks = session.scalars(select(BlockRow).where(BlockRow.trip_id == key).order_by(BlockRow.position))
            legs = session.scalars(select(LegRow).where(LegRow.trip_id == key).order_by(LegRow.position))
            window = {name: getattr(trip, name) for name in TripWindow.model_fields}
            return TripRecord(
                TripWindow.model_validate(window),
                ScheduleState(blocks=tuple(map(_block, blocks)), legs=tuple(map(_leg, legs))),
            )

    def save(self, trip_id: str, record: TripRecord) -> None:
        """일정은 통째로 바꾼다: 이 여행의 blocks·legs 를 지우고 다시 넣는다."""
        key = _required_key(trip_id)
        window = record.trip
        with self.database.transaction() as session, session.begin_nested():
            trip = session.get(TripRow, key)
            if trip is None:
                trip = TripRow(id=key)
                session.add(trip)
            trip.start_date, trip.end_date = window.start_date, window.end_date
            trip.day_start, trip.day_end = window.day_start, window.day_end
            trip.transport_mode = window.transport_mode
            session.flush()
            session.execute(delete(LegRow).where(LegRow.trip_id == key))
            session.execute(delete(BlockRow).where(BlockRow.trip_id == key))
            schedule = record.schedule
            if schedule.blocks:
                session.execute(insert(BlockRow), [_block_values(key, i, b) for i, b in enumerate(schedule.blocks)])
            if schedule.legs:
                session.execute(insert(LegRow), [_leg_values(key, i, leg) for i, leg in enumerate(schedule.legs)])


class SqlSnapshotRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def next_version(self, trip_id: str) -> int:
        key = _trip_key(trip_id)
        if key is None:
            return 1
        with self.database.transaction() as session:
            latest = session.scalar(
                select(func.max(ScheduleSnapshotRow.version)).where(ScheduleSnapshotRow.trip_id == key)
            )
            return (latest or 0) + 1

    def save(self, snapshot: ScheduleSnapshot) -> None:
        key = _required_key(snapshot.trip_id)
        with self.database.transaction() as session, session.begin_nested():
            session.add(
                ScheduleSnapshotRow(
                    trip_id=key,
                    version=snapshot.version,
                    payload=snapshot.payload,
                    reason=snapshot.reason.value,
                    created_at=snapshot.created_at,
                )
            )

    def latest(self, trip_id: str, reason: SnapshotReason) -> ScheduleSnapshot | None:
        key = _trip_key(trip_id)
        if key is None:
            return None
        with self.database.transaction() as session:
            row = session.scalars(
                select(ScheduleSnapshotRow)
                .where(ScheduleSnapshotRow.trip_id == key, ScheduleSnapshotRow.reason == reason.value)
                .order_by(ScheduleSnapshotRow.version.desc())
                .limit(1)
            ).first()
            if row is None:
                return None
            return ScheduleSnapshot(
                trip_id=trip_id,
                version=row.version,
                payload=row.payload,
                reason=SnapshotReason(row.reason),
                created_at=row.created_at,
            )

    def delete(self, snapshot: ScheduleSnapshot) -> None:
        key = _required_key(snapshot.trip_id)
        with self.database.transaction() as session, session.begin_nested():
            session.execute(
                delete(ScheduleSnapshotRow).where(
                    ScheduleSnapshotRow.trip_id == key, ScheduleSnapshotRow.version == snapshot.version
                )
            )
