"""FR-006 저장소 계약: 메모리 구현과 DB 구현(SQLite·PostgreSQL)이 같게 동작한다.

- `memory`·`sqlite` 는 항상 돈다. SQLite 는 alembic 마이그레이션으로 만든 메모리 DB 다.
- `postgres` 는 `TEST_DATABASE_URL`(예: postgresql://pinandfill:pinandfill@localhost:5432/pinandfill_test)이
  있을 때만 돈다. 그 DB 의 스키마는 시험마다 지우고 다시 만든다. 잘못 가리켜 데이터를 지우지 않도록
  지울 바로 그 연결에서 실제 DB 이름(`current_database()`)을 읽어 `_test` 로 끝나지 않으면 멈춘다.
  URL 경로만 보면 `?dbname=` 쿼리가 경로를 덮어써 다른 DB 를 지울 수 있다.
"""

import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import Connection, StaticPool, inspect, select, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.db.models import Base, BlockRow, ScheduleSnapshotRow
from app.db.session import Database
from app.main import create_app
from app.modules.engine.schemas import (
    CalculationContext,
    KakaoPlaceRef,
    RecomputeInput,
    ScheduleState,
    SessionCoordinate,
    StoredLeg,
)
from app.modules.trips.edit_history import (
    EditHistory,
    InMemorySnapshotRepository,
    NothingToUndoError,
    ScheduleSnapshot,
    SnapshotReason,
    SnapshotRepository,
)
from app.modules.trips.repository import FakeTripRepository, TripRecord, TripRepository
from app.modules.trips.schemas import DeleteBlockRequest, UndoRequest, UpdateBlockRequest
from app.modules.trips.service import TripService
from app.modules.trips.sql_repository import SqlSnapshotRepository, SqlTripRepository
from tests.unit.engine.test_service import _block, _engine, _trip

BACKEND_DIR = Path(__file__).resolve().parents[2]
POSTGRES_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
needs_postgres = pytest.mark.skipif(not POSTGRES_URL, reason="TEST_DATABASE_URL is not set")
DB_KINDS = ["sqlite", pytest.param("postgres", marks=needs_postgres)]

TRIP = str(uuid.uuid4())
KAKAO_REF = KakaoPlaceRef.model_validate({"kakaoPlaceId": "123", "placeUrl": "https://place.map.kakao.com/123"})
COORDS = {"123": SessionCoordinate(lat=35.1234567, lng=129.7654321)}


def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["configure_logger"] = False
    return config


def upgrade(database: Database, revision: str = "head") -> None:
    config = alembic_config()
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def downgrade(database: Database, revision: str = "base") -> None:
    config = alembic_config()
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, revision)


def require_test_database(connection: Connection) -> None:
    """Refuse to wipe a database whose name does not mark it as a test database.

    Reads the name from the connection that will run the DROP, not from the URL text:
    a `?dbname=` query overrides the URL path, so the path alone can name the wrong database.
    """
    name = connection.execute(text("SELECT current_database()")).scalar_one()
    if not str(name or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must connect to a database ending in _test; refusing to drop its schema")


def open_database(kind: str, url: str = POSTGRES_URL) -> Database:
    if kind == "sqlite":
        return Database("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    database = Database(url)
    try:
        with database.engine.begin() as connection:
            require_test_database(connection)
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    except BaseException:
        database.dispose()
        raise
    return database


@pytest.fixture(params=DB_KINDS)
def database(request: pytest.FixtureRequest) -> Iterator[Database]:
    database = open_database(request.param)
    upgrade(database)
    yield database
    database.dispose()


@dataclass
class Stores:
    trips: TripRepository
    snapshots: SnapshotRepository
    transaction: Callable[[], Any]


@pytest.fixture(params=["memory", *DB_KINDS])
def stores(request: pytest.FixtureRequest) -> Iterator[Stores]:
    if request.param == "memory":
        yield Stores(FakeTripRepository({}), InMemorySnapshotRepository(), nullcontext)
        return
    database = open_database(request.param)
    upgrade(database)
    yield Stores(SqlTripRepository(database), SqlSnapshotRepository(database), database.transaction)
    database.dispose()


def kakao_state() -> tuple[ScheduleState, Any]:
    """d(공공·고정) → k(카카오) → e(공공). 좌표로 계산해 구간·시각이 채워진 상태."""
    engine, _, _ = _engine(("d", "e", "h"))
    state = ScheduleState(
        blocks=(
            _block("d", 1, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("k", 2, ref=KAKAO_REF, arrive=None, depart=None),
            _block("e", 3, arrive=None, depart=None),
            _block("h", 1, arrive=time(10), depart=time(10, 30), day_no=2),
        )
    )
    result = engine.recompute(
        RecomputeInput(trip=_trip(end_date=date(2026, 11, 3)), schedule=state, from_block_id="d"),
        context=CalculationContext(session_coords=COORDS),
    )
    assert result.state.legs, "fixture must contain legs"
    return result.state, engine


def record() -> TripRecord:
    state, _ = kakao_state()
    extra = StoredLeg(
        id="leg-unknown", from_block_id="e", to_block_id="d", mode="WALK", source="UNKNOWN", lookup_failed=True
    )
    return TripRecord(_trip(end_date=date(2026, 11, 3)), ScheduleState(blocks=state.blocks, legs=(*state.legs, extra)))


# ---- 저장소 계약(메모리·SQLite·PostgreSQL) ----


def test_trip_round_trip_keeps_state_exactly(stores: Stores):
    expected = record()
    stores.trips.save(TRIP, expected)
    assert stores.trips.get(TRIP) == expected


def test_save_replaces_whole_schedule(stores: Stores):
    full = record()
    stores.trips.save(TRIP, full)
    smaller = TripRecord(full.trip, ScheduleState(blocks=full.schedule.blocks[:1]))
    stores.trips.save(TRIP, smaller)
    assert stores.trips.get(TRIP) == smaller
    stores.trips.save(TRIP, TripRecord(full.trip, ScheduleState()))
    assert stores.trips.get(TRIP) == TripRecord(full.trip, ScheduleState())


@pytest.mark.parametrize("trip_id", [str(uuid.uuid4()), "not-a-uuid"])
def test_unknown_trip_is_none(stores: Stores, trip_id: str):
    assert stores.trips.get(trip_id) is None
    assert stores.snapshots.latest(trip_id, SnapshotReason.EDIT) is None
    assert stores.snapshots.next_version(trip_id) == 1


def snapshot(version: int, reason: SnapshotReason, state: ScheduleState) -> ScheduleSnapshot:
    return ScheduleSnapshot(
        trip_id=TRIP,
        version=version,
        payload=state.model_dump(mode="json", by_alias=True),
        reason=reason,
        created_at=datetime(2026, 11, 2, 1, 2, 3, 456789, tzinfo=UTC),
    )


def test_snapshot_contract(stores: Stores):
    full = record()
    stores.trips.save(TRIP, full)
    assert stores.snapshots.next_version(TRIP) == 1
    first = snapshot(1, SnapshotReason.EDIT, full.schedule)
    stores.snapshots.save(first)
    stores.snapshots.save(snapshot(2, SnapshotReason.GENERATE, ScheduleState()))
    assert stores.snapshots.next_version(TRIP) == 3

    latest = stores.snapshots.latest(TRIP, SnapshotReason.EDIT)
    assert latest == first
    assert ScheduleState.model_validate(latest.payload) == full.schedule
    assert stores.snapshots.latest(TRIP, SnapshotReason.PLAN_B) is None

    stores.snapshots.delete(first)
    assert stores.snapshots.latest(TRIP, SnapshotReason.EDIT) is None
    assert stores.snapshots.latest(TRIP, SnapshotReason.GENERATE) is not None


def test_edit_history_one_step_undo(stores: Stores):
    full = record()
    stores.trips.save(TRIP, full)
    history = EditHistory(stores.snapshots)
    history.record_before_edit(TRIP, ScheduleState())
    history.record_before_edit(TRIP, full.schedule)
    assert history.undo(TRIP) == full.schedule
    with pytest.raises(NothingToUndoError):
        history.undo(TRIP)


# ---- 서비스 편집 한 번의 원자성(DB) ----


def db_service(database: Database) -> tuple[TripService, SqlTripRepository]:
    state, engine = kakao_state()
    repository = SqlTripRepository(database)
    repository.save(TRIP, TripRecord(_trip(end_date=date(2026, 11, 3)), state))
    service = TripService(
        repository,
        engine,
        lambda place: 30,
        history=EditHistory(SqlSnapshotRepository(database)),
        transaction=database.transaction,
    )
    return service, repository


def test_service_edit_and_undo_persist(database: Database):
    service, repository = db_service(database)
    before = repository.get(TRIP)
    service.update_block(TRIP, "e", UpdateBlockRequest(stay_min=60, session_coords=COORDS))
    edited = repository.get(TRIP)
    assert edited != before
    service.undo(TRIP, UndoRequest(session_coords=COORDS))
    assert repository.get(TRIP) == before
    with pytest.raises(NothingToUndoError):
        service.undo(TRIP, UndoRequest())


class FailingSave(SqlTripRepository):
    """일정을 DB 에 쓴 다음 실패한다. 같은 트랜잭션의 스냅샷 기록도 함께 롤백되어야 한다."""

    def save(self, trip_id: str, record: TripRecord) -> None:
        super().save(trip_id, record)
        raise RuntimeError("storage unavailable")


def test_failed_edit_rolls_back_schedule_and_snapshot(database: Database):
    service, repository = db_service(database)
    service.update_block(TRIP, "e", UpdateBlockRequest(stay_min=60, session_coords=COORDS))
    current = repository.get(TRIP)
    point = service.history.latest_edit(TRIP)

    service.repository = FailingSave(database)
    with pytest.raises(RuntimeError):
        service.delete_block(TRIP, "e", DeleteBlockRequest())

    assert repository.get(TRIP) == current
    assert service.history.latest_edit(TRIP) == point


def test_failed_undo_keeps_snapshot(database: Database):
    service, repository = db_service(database)
    service.update_block(TRIP, "e", UpdateBlockRequest(stay_min=60, session_coords=COORDS))
    current = repository.get(TRIP)
    point = service.history.latest_edit(TRIP)

    service.repository = FailingSave(database)
    with pytest.raises(RuntimeError):
        service.undo(TRIP, UndoRequest())

    assert repository.get(TRIP) == current
    assert service.history.latest_edit(TRIP) == point


def test_db_error_inside_edit_is_not_masked(database: Database):
    """스냅샷 쓰기가 DB 제약 오류로 실패해도 보상 코드가 세션 오류로 원래 예외를 가리지 않는다."""
    service, repository = db_service(database)
    current = repository.get(TRIP)
    taken = SqlSnapshotRepository(database)
    taken.save(snapshot(1, SnapshotReason.GENERATE, ScheduleState()))

    class StaleVersion(SqlSnapshotRepository):
        def next_version(self, trip_id: str) -> int:
            return 1  # 이미 있는 버전 → UNIQUE(trip_id, version) 위반

    service.history = EditHistory(StaleVersion(database))
    with pytest.raises(IntegrityError):
        service.update_block(TRIP, "e", UpdateBlockRequest(stay_min=60))
    assert repository.get(TRIP) == current
    assert service.history.latest_edit(TRIP) is None


# ---- 카카오 장소명·좌표는 저장하지 않는다 ----


def test_db_never_stores_kakao_name_or_coordinates(database: Database):
    service, _ = db_service(database)
    service.update_block(TRIP, "e", UpdateBlockRequest(stay_min=60, session_coords=COORDS))
    inspector = inspect(database.engine)
    # places 는 공공 장소(TourAPI 등)의 이름·좌표를 저장하는 테이블이다. 카카오 장소는 일정 테이블에만 들어간다.
    trip_tables = ("trips", "blocks", "legs", "schedule_snapshots")
    columns = {column["name"] for table in trip_tables for column in inspector.get_columns(table)}
    assert not {"name", "lat", "lng", "place_name", "x", "y"} & columns
    with database.engine.connect() as connection:
        dumped = ""
        for table in Base.metadata.sorted_tables:
            dumped += repr(connection.execute(select(table)).all())
    for secret in ("35.1234567", "129.7654321", "35.123", "129.765"):
        assert secret not in dumped
    with database.transaction() as session:
        kakao = session.scalars(select(BlockRow).where(BlockRow.kakao_place_id.is_not(None))).one()
        assert (kakao.kakao_place_id, kakao.kakao_place_url) == ("123", "https://place.map.kakao.com/123")
        payloads = session.scalars(select(ScheduleSnapshotRow.payload)).all()
    assert payloads and all("35.123" not in repr(payload) for payload in payloads)


# ---- 마이그레이션 ----


def test_migration_matches_models_and_downgrades(database: Database):
    with database.engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata)
    assert diff == []
    downgrade(database)
    assert set(inspect(database.engine).get_table_names()) <= {"alembic_version"}
    upgrade(database)
    tables = {"trips", "blocks", "legs", "schedule_snapshots"}
    tables |= {"places", "place_hours", "data_sources", "ingestion_runs"}
    assert tables <= set(inspect(database.engine).get_table_names())
    with database.engine.connect() as connection:
        sources = connection.execute(
            text("SELECT id, kind, refresh_cycle, daily_call_limit, enabled FROM data_sources ORDER BY id")
        ).all()
    assert [tuple(row) for row in sources] == [
        ("data06", "API", "DAY", None, False),
        ("data07", "API", "DAY", None, False),
        ("tourapi", "API", "MONTH", 1000, True),
    ]


def test_downgrade_to_0001_keeps_trip_tables(database: Database):
    downgrade(database, "0001")
    tables = set(inspect(database.engine).get_table_names())
    assert {"trips", "blocks", "legs", "schedule_snapshots"} <= tables
    assert not {"places", "place_hours", "data_sources", "ingestion_runs"} & tables


# ---- 기본 구성(DATABASE_URL) ----


def test_default_app_uses_database_when_url_is_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite:///{tmp_path / 'app.db'}"
    upgrade(Database(url))
    monkeypatch.setenv("DATABASE_URL", url)
    trip = {"dates": {"start": "2026-11-17", "end": "2026-11-17"}, "dayStart": "09:00", "dayEnd": "20:00"}
    block = {"dayNo": 1, "place": {"placeId": "130166"}, "isFixed": False, "origin": "USER", "stayMin": 40}

    with TestClient(create_app()) as client:
        trip_id = client.post("/api/trips", json={**trip, "mode": "TRANSIT"}).json()["tripId"]
        assert client.post(f"/api/trips/{trip_id}/blocks", json=block).status_code == 200
    # 새 앱(=재시작)에서도 여행과 되돌리기 이력이 남아 있다.
    with TestClient(create_app()) as client:
        detail = client.get(f"/api/trips/{trip_id}")
        assert detail.status_code == 200
        assert len(detail.json()["schedule"]["days"][0]["blocks"]) == 1
        undone = client.post(f"/api/trips/{trip_id}/undo")
        assert undone.status_code == 200
        assert undone.json()["schedule"]["days"][0]["blocks"] == []
        assert client.get("/api/trips/not-a-uuid").status_code == 404


class _NamedConnection:
    """`SELECT current_database()` 에 정해 둔 이름을 돌려주는 가짜 연결."""

    def __init__(self, name: str | None) -> None:
        self.name = name
        self.statements: list[str] = []

    def execute(self, statement: Any) -> Any:
        self.statements.append(str(statement))
        return type("Result", (), {"scalar_one": lambda _: self.name})()


@pytest.mark.parametrize("name", ["pinandfill", "test_pinandfill", "pinandfill_test_backup", "", None])
def test_non_test_database_is_never_wiped(name: str | None):
    connection = _NamedConnection(name)
    with pytest.raises(pytest.fail.Exception, match="_test"):
        require_test_database(connection)  # type: ignore[arg-type]
    assert connection.statements == ["SELECT current_database()"]


def test_test_database_name_is_accepted():
    require_test_database(_NamedConnection("pinandfill_test"))  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ["pinandfill", "postgres"])
def test_open_database_stops_before_any_schema_sql_and_closes_the_engine(name: str, monkeypatch: pytest.MonkeyPatch):
    # 경로는 _test 지만 ?dbname= 쿼리가 실제 연결 DB 를 바꾸는 URL. 실제 DB 이름으로 막고,
    # DROP·CREATE 를 하나도 보내지 않은 채 엔진을 닫아야 한다. 실제 DB 에는 붙지 않는다.
    connection = _NamedConnection(name)
    opened: list[Any] = []

    class _FakeDatabase:
        def __init__(self, url: str) -> None:
            self.url = url
            self.disposed = False
            self.engine = self
            opened.append(self)

        @contextmanager
        def begin(self) -> Iterator[_NamedConnection]:
            yield connection

        def dispose(self) -> None:
            self.disposed = True

    monkeypatch.setitem(globals(), "Database", _FakeDatabase)
    url = f"postgresql://u:p@localhost:5432/pinandfill_test?dbname={name}"
    with pytest.raises(pytest.fail.Exception, match="_test"):
        open_database("postgres", url)
    assert connection.statements == ["SELECT current_database()"]
    assert [(db.url, db.disposed) for db in opened] == [(url, True)]


def test_alembic_ini_is_ascii_so_any_locale_can_read_it():
    # alembic 은 alembic.ini 를 로캘 인코딩으로 읽는다. 한국어 Windows(cp949)에서 UTF-8 한글 주석은 깨진다.
    (BACKEND_DIR / "alembic.ini").read_bytes().decode("ascii")
