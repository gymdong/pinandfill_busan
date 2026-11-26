"""SDD 5.2 의 테이블 중 지금 저장하는 것만: 일정 도메인(trips·blocks·legs·schedule_snapshots)과
공공 장소·수집 기록(places·place_hours·data_sources·ingestion_runs, FR-016).

운영 DB 는 PostgreSQL 이다. 시험에서 SQLite 로도 만들 수 있게 JSONB 는 PostgreSQL 에서만 쓰고 그 밖에서는 JSON 이다.

SDD 와 다른 점(현재 엔진 상태 `ScheduleState` 를 손실 없이 저장하기 위함):
- blocks·legs 의 id 는 엔진이 정하는 문자열이며 여행 안에서만 유일하다. 그래서 (trip_id, id) 가 PK 다.
  legs 에도 trip_id 를 두어 (trip_id, from/to_block_id) 로 blocks 를 참조한다.
- blocks.place_id 는 FK 없는 문자열이다(places 에 없는 카카오·미등록 장소도 담는다). 카카오 장소는 ID·URL 만
  저장한다(`KakaoPlaceRef`). 카카오 장소명·좌표는 저장하지 않는다(세션 한정).
- position 은 저장한 순서(튜플 순서)를 그대로 되살리기 위한 열이다.
- legs.computed_at 은 null 일 수 있고(경로 미조회), time_semantics·lookup_failed 를 함께 저장한다.
- blocks.warnings 는 저장하지 않는다. 경고는 조회할 때마다 엔진이 다시 계산한다.
- trips 는 일정 계산에 쓰는 열만 둔다. user_id·장소·동행·취향·예산·만료 등은 해당 기능이 저장할 때 추가한다.

공공 장소·수집 기록에서 SDD 와 다른 점:
- places.id 는 UUID 가 아니라 공공 원본 ID(TourAPI contentid) 문자열이다(A-3, 결정 D2). source_ref 에도 같은 값을
  둔다. 다른 공공 소스의 ID 는 겹치지 않게 접두어를 붙인다(예: `busan:…`).
- 표본 CSV 에 빈 값이 있어 default_stay_min·indoor_outdoor·ref_date 는 NULL 을 허용한다(값을 지어내지 않음, NFR-012).
- places 에 address(주소)·source_org(장소 상세의 출처 기관)·collected_at(배치가 마지막으로 갱신한 시각) 열을 더한다.
  ref_date 는 수동 확인 기준일(CSV checked_at)이며 배치가 덮어쓰지 않는다(MANUAL 영업시간의 기준일, NFR-012).
  rating 은 쓰는 기능이 아직 없어 두지 않는다.
- place_hours 는 (place_id, day_type) 가 유일하다(A-4). ingestion_runs 에 rejected_count(응답 검증 거절 건수, A-4)와
  alerted_at(관리자 알림을 보낸 시각, 알림 중복 억제용)을 더한다. finished_at 은 실행 중이면 NULL 이다.
"""

import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
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
            "ck": "ck_%(table_name)s_%(constraint_name)s",
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


class PlaceRow(Base):
    __tablename__ = "places"

    # 공공 원본 ID(TourAPI contentid). 다른 소스는 접두어를 붙인다(예: `busan:…`).
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    lat: Mapped[float] = mapped_column(Double)
    lng: Mapped[float] = mapped_column(Double)
    category: Mapped[str] = mapped_column(String(50))
    # PUBLIC(공공 DB) / USER_SELECTED(SDD D6, 아직 저장하지 않음)
    source: Mapped[str] = mapped_column(String(20))
    source_ref: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    closed_days_text: Mapped[str | None] = mapped_column(String(200))
    default_stay_min: Mapped[int | None] = mapped_column(SmallInteger)
    indoor_outdoor: Mapped[str | None] = mapped_column(String(10))
    adm_dong_code: Mapped[str | None] = mapped_column(String(20))
    # 장소 상세의 출처 기관 표기(예: '한국관광공사 TourAPI, 비짓부산')
    source_org: Mapped[str | None] = mapped_column(String(200))
    # 수동 확인 기준일(CSV checked_at). 배치 수집은 바꾸지 않는다(NFR-012).
    ref_date: Mapped[date | None] = mapped_column(Date)
    # 배치가 이름·좌표·주소를 마지막으로 갱신한 시각
    collected_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


class PlaceHourRow(Base):
    __tablename__ = "place_hours"
    __table_args__ = (
        UniqueConstraint("place_id", "day_type"),
        CheckConstraint("day_type IN ('MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN', 'HOLIDAY')", name="day_type"),
        CheckConstraint("origin IN ('PARSED', 'MANUAL')", name="origin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    place_id: Mapped[str] = mapped_column(String(64), ForeignKey("places.id", ondelete="CASCADE"))
    # MON~SUN 또는 HOLIDAY(SDD). 앱은 아직 HOLIDAY 행을 읽지 않는다.
    day_type: Mapped[str] = mapped_column(String(10))
    # 시각이 NULL 이면 '확인 필요'다(지어내지 않음, NFR-012).
    open_time: Mapped[time | None] = mapped_column(Time)
    close_time: Mapped[time | None] = mapped_column(Time)
    break_start: Mapped[time | None] = mapped_column(Time)
    break_end: Mapped[time | None] = mapped_column(Time)
    is_closed: Mapped[bool] = mapped_column(Boolean)
    # PARSED(파서) / MANUAL(수동 보정)
    origin: Mapped[str] = mapped_column(String(10))


class DataSourceRow(Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    # API / CSV / SDK
    kind: Mapped[str] = mapped_column(String(10))
    # MONTH / DAY / MINUTE
    refresh_cycle: Mapped[str] = mapped_column(String(20))
    daily_call_limit: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean)


class IngestionRunRow(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        Index(None, "source_id", "started_at"),
        CheckConstraint("status IN ('RUNNING', 'SUCCESS', 'FAILED', 'SKIPPED')", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(String(30), ForeignKey("data_sources.id"))
    started_at: Mapped[datetime] = mapped_column(UtcDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    # SUCCESS / FAILED / SKIPPED. RUNNING 은 실행 중(finished_at 이 NULL)인 행이다.
    status: Mapped[str] = mapped_column(String(10))
    record_count: Mapped[int | None] = mapped_column(Integer)
    rejected_count: Mapped[int | None] = mapped_column(Integer)
    call_count: Mapped[int | None] = mapped_column(Integer)
    as_of: Mapped[datetime | None] = mapped_column(UtcDateTime)
    # 민감정보(serviceKey 등)를 넣지 않는다(NFR-010).
    error_message: Mapped[str | None] = mapped_column(Text)
    # 이 실행으로 관리자 알림을 보낸 시각. 알림 중복 억제에 쓴다.
    alerted_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
