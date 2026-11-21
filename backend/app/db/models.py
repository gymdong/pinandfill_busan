"""SDD 5.2 의 일정 도메인 테이블 중 지금 저장하는 것만(trips·blocks·legs·schedule_snapshots).

운영 DB 는 PostgreSQL 이다. 시험에서 SQLite 로도 만들 수 있게 JSONB 는 PostgreSQL 에서만 쓰고 그 밖에서는 JSON 이다.

SDD 와 다른 점(현재 엔진 상태 `ScheduleState` 를 손실 없이 저장하기 위함):
- blocks·legs 의 id 는 엔진이 정하는 문자열이며 여행 안에서만 유일하다. 그래서 (trip_id, id) 가 PK 다.
  legs 에도 trip_id 를 두어 (trip_id, from/to_block_id) 로 blocks 를 참조한다.
- places 테이블이 아직 없어 blocks.place_id 는 FK 없는 문자열이다. 카카오 장소는 ID·URL 만 저장한다
  (`KakaoPlaceRef`). 카카오 장소명·좌표는 저장하지 않는다(세션 한정).
- position 은 저장한 순서(튜플 순서)를 그대로 되살리기 위한 열이다.
- legs.computed_at 은 null 일 수 있고(경로 미조회), time_semantics·lookup_failed 를 함께 저장한다.
- blocks.warnings 는 저장하지 않는다. 경고는 조회할 때마다 엔진이 다시 계산한다.
- trips 는 일정 계산에 쓰는 열만 둔다. user_id·장소·동행·취향·예산·만료 등은 해당 기능이 저장할 때 추가한다.
"""

import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

JsonDocument = JSON().with_variant(JSONB(), "postgresql")


class UtcDateTime(TypeDecorator[datetime]):
    """TIMESTAMP WITH TIME ZONE. 항상 UTC aware 로 돌려준다(SQLite 는 시간대를 저장하지 않는다)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    # 제약 이름을 고정해 마이그레이션과 모델이 DB 에 같은 이름을 만들게 한다.
    metadata = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        }
    )


class TripRow(Base):
    __tablename__ = "trips"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    # 비회원 익명 세션 키. 지금은 발급만 하고 저장·검증하지 않는다(API-003).
    session_key: Mapped[str | None] = mapped_column(String(64))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    day_start: Mapped[time] = mapped_column(Time)
    day_end: Mapped[time] = mapped_column(Time)
    transport_mode: Mapped[str] = mapped_column(String(10))


class BlockRow(Base):
    __tablename__ = "blocks"

    trip_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("trips.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger)
    day_no: Mapped[int] = mapped_column(SmallInteger)
    seq: Mapped[int] = mapped_column(SmallInteger)
    place_kind: Mapped[str] = mapped_column(String(10))
    place_id: Mapped[str | None] = mapped_column(String(64))
    kakao_place_id: Mapped[str | None] = mapped_column(String(32))
    kakao_place_url: Mapped[str | None] = mapped_column(String(255))
    is_fixed: Mapped[bool] = mapped_column(Boolean)
    fixed_start: Mapped[time | None] = mapped_column(Time)
    fixed_end: Mapped[time | None] = mapped_column(Time)
    stay_min: Mapped[int] = mapped_column(SmallInteger)
    arrive_at: Mapped[time | None] = mapped_column(Time)
    depart_at: Mapped[time | None] = mapped_column(Time)
    origin: Mapped[str] = mapped_column(String(10))


class LegRow(Base):
    __tablename__ = "legs"
    __table_args__ = (
        ForeignKeyConstraint(["trip_id", "from_block_id"], ["blocks.trip_id", "blocks.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["trip_id", "to_block_id"], ["blocks.trip_id", "blocks.id"], ondelete="CASCADE"),
    )

    # trips 참조는 blocks 를 거친다((trip_id, from/to_block_id) → blocks).
    trip_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger)
    from_block_id: Mapped[str] = mapped_column(String(64))
    to_block_id: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(10))
    duration_min: Mapped[int | None] = mapped_column(SmallInteger)
    computed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    source: Mapped[str] = mapped_column(String(20))
    time_semantics: Mapped[str] = mapped_column(String(30))
    lookup_failed: Mapped[bool] = mapped_column(Boolean)


class ScheduleSnapshotRow(Base):
    __tablename__ = "schedule_snapshots"
    __table_args__ = (UniqueConstraint("trip_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    trip_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("trips.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    # 변경 전 일정 전체: ScheduleState.model_dump(mode="json", by_alias=True). 장소 참조만 담는다.
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDocument)
    reason: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
