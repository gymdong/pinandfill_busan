"""FR-016 places·place_hours 저장소와 시드 명령.

SQLite(alembic)는 항상, PostgreSQL 은 TEST_DATABASE_URL 이 있을 때 돈다.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.batch import cli
from app.batch.jobs.public_places import PublicPlaceRecord
from app.db.models import IngestionRunRow, PlaceHourRow, PlaceRow
from app.db.session import Database
from app.modules.places.db_repository import SqlPlaceStore
from app.modules.places.samples import SAMPLE_DIR, SamplePlace, load_sample_places
from tests.integration.test_db_persistence import DB_KINDS, open_database, upgrade

SEEDED_AT = datetime(2026, 11, 26, 1, 0, tzinfo=UTC)
COLLECTED_AT = datetime(2026, 11, 27, 3, 0, tzinfo=UTC)


@pytest.fixture(params=DB_KINDS)
def database(request: pytest.FixtureRequest) -> Iterator[Database]:
    database = open_database(request.param)
    upgrade(database)
    yield database
    database.dispose()


def by_id(places: list[SamplePlace]) -> list[SamplePlace]:
    return sorted(places, key=lambda item: item.place.id)


def table_counts(database: Database) -> tuple[int, int]:
    with database.transaction() as session:
        places = session.scalar(select(func.count()).select_from(PlaceRow))
        hours = session.scalar(select(func.count()).select_from(PlaceHourRow))
    return places or 0, hours or 0


def test_seeded_places_load_back_like_the_csv(database: Database):
    expected = by_id(load_sample_places().samples())
    assert expected and any(item.hours for item in expected)
    store = SqlPlaceStore(database)

    result = store.upsert_seed(expected, SEEDED_AT)
    assert (result.places, result.changed) == (len(expected), len(expected))

    # 장소·영업시간·origin·체류시간·ref_date·source_org·address 등 SamplePlace 전체가 같다(A2-2).
    assert store.load() == expected
    assert store.public_ids() == [item.place.id for item in expected]
    assert all(item.hours_origin == dict.fromkeys(item.hours, "MANUAL") for item in store.load())


def test_seed_twice_is_idempotent(database: Database):
    expected = by_id(load_sample_places().samples())
    store = SqlPlaceStore(database)
    store.upsert_seed(expected, SEEDED_AT)
    with database.transaction() as session:
        hour_ids = set(session.scalars(select(PlaceHourRow.id)))
    counts = table_counts(database)

    later = datetime(2026, 11, 28, tzinfo=UTC)
    result = store.upsert_seed(expected, later)

    assert (result.places, result.changed, result.pruned) == (len(expected), 0, 0)
    assert table_counts(database) == counts
    assert store.load() == expected
    with database.transaction() as session:
        assert set(session.scalars(select(PlaceHourRow.id))) == hour_ids
        # 값이 그대로이면 updated_at 도 그대로다.
        assert set(session.scalars(select(PlaceRow.updated_at))) == {SEEDED_AT}


def test_collected_values_survive_reseed_and_manual_values_survive_collection(database: Database):
    expected = by_id(load_sample_places().samples())
    first = expected[0]
    store = SqlPlaceStore(database)
    store.upsert_seed(expected, SEEDED_AT)
    record = PublicPlaceRecord(first.place.id, "새 이름", 35.5, 129.5, "부산광역시 새 주소")

    assert store.update_collected([record, PublicPlaceRecord("unknown", "x", 35.0, 129.0, "")], COLLECTED_AT) == 1
    store.upsert_seed(expected, SEEDED_AT)

    loaded = store.load()[0]
    assert (loaded.place.name, loaded.place.lat, loaded.place.lng, loaded.address) == (
        "새 이름",
        35.5,
        129.5,
        "부산광역시 새 주소",
    )
    # 수동 값(ref_date·영업시간·origin·source_org)은 수집이 바꾸지 않는다(NFR-012).
    assert (loaded.ref_date, loaded.hours, loaded.hours_origin, loaded.source_org) == (
        first.ref_date,
        first.hours,
        first.hours_origin,
        first.source_org,
    )
    with database.transaction() as session:
        row = session.get(PlaceRow, first.place.id)
        assert row is not None and row.collected_at == COLLECTED_AT
    assert store.public_ids() == [item.place.id for item in expected]


HOURS_HEADER = "tourapi_contentid,day_type,open_time,close_time,break_start,break_end,is_closed,origin\n"


def write_samples(directory: Path, hours: str) -> None:
    places = "\ufeffname,lat,lng,category,tourapi_contentid,checked_at\n예시 공원,35.1,129.1,관광지,100,2026-11-01\n"
    (directory / "places_sample.csv").write_text(places, encoding="utf-8")
    (directory / "place_hours.csv").write_text(HOURS_HEADER + hours, encoding="utf-8")


def test_reseed_keeps_hours_rows_missing_from_the_csv_unless_pruned(database: Database, tmp_path: Path):
    write_samples(tmp_path, "100,MON,09:00,18:00,12:00,13:00,FALSE,PARSED\n100,TUE,,,,,TRUE,\n")
    store = SqlPlaceStore(database)
    assert cli.seed_places(database, tmp_path).places == 1

    loaded = store.load()[0]
    assert loaded.ref_date == date(2026, 11, 1)
    assert loaded.stay_min is None and loaded.address is None and loaded.source_org is None
    assert loaded.hours["MON"].break_start == time(12)
    # origin 이 빈 행은 수동 CSV 이므로 MANUAL 이다.
    assert loaded.hours_origin == {"MON": "PARSED", "TUE": "MANUAL"}

    write_samples(tmp_path, "100,MON,10:00,18:00,,,FALSE,PARSED\n")
    result = cli.seed_places(database, tmp_path)

    # CSV 에서 빠진 TUE 는 --prune 없이는 지우지 않는다.
    assert (result.kept_unlisted, result.pruned) == (1, 0)
    loaded = store.load()[0]
    assert set(loaded.hours) == {"MON", "TUE"} and loaded.hours["MON"].open_time == time(10)

    result = cli.seed_places(database, tmp_path, prune=True)

    assert (result.kept_unlisted, result.pruned) == (0, 1)
    assert set(store.load()[0].hours) == {"MON"}
    assert table_counts(database) == (1, 1)


def test_manual_db_row_survives_reseed(database: Database, tmp_path: Path):
    write_samples(tmp_path, "100,MON,09:00,18:00,,,FALSE,MANUAL\n")
    cli.seed_places(database, tmp_path)
    with database.transaction() as session:
        session.add(PlaceHourRow(place_id="100", day_type="WED", is_closed=True, origin="MANUAL"))

    result = cli.seed_places(database, tmp_path)

    assert result.kept_unlisted == 1
    assert store_hours(database) == {"MON", "WED"}


def test_invalid_csv_hours_row_keeps_the_db_row_even_when_pruning(
    database: Database, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    write_samples(tmp_path, "100,MON,09:00,18:00,,,FALSE,MANUAL\n100,TUE,09:00,18:00,,,FALSE,MANUAL\n")
    cli.seed_places(database, tmp_path)
    # 초가 붙은 시각·알 수 없는 origin 은 읽지 못한다. 그 요일의 DB 행은 지우지도 바꾸지도 않는다.
    write_samples(tmp_path, "100,MON,09:00:30,18:00,,,FALSE,MANUAL\n100,TUE,09:00,19:00,,,FALSE,AUTO\n")

    result = cli.seed_places(database, tmp_path, prune=True)

    assert (result.kept_invalid, result.pruned) == (2, 0)
    assert "invalid_in_csv=2" in caplog.text
    hours = SqlPlaceStore(database).load()[0].hours
    assert (hours["MON"].open_time, hours["TUE"].close_time) == (time(9), time(18))


def test_load_skips_non_weekday_hours_rows(database: Database, tmp_path: Path, caplog: pytest.LogCaptureFixture):
    write_samples(tmp_path, "100,MON,09:00,18:00,,,FALSE,MANUAL\n")
    cli.seed_places(database, tmp_path)
    with database.transaction() as session:
        session.add(PlaceHourRow(place_id="100", day_type="HOLIDAY", is_closed=True, origin="MANUAL"))

    loaded = SqlPlaceStore(database).load()[0]

    assert set(loaded.hours) == {"MON"} and set(loaded.hours_origin) == {"MON"}
    assert "day_type_not_weekday=1" in caplog.text


@pytest.mark.parametrize(
    ("row", "constraint"),
    [
        ({"day_type": "MONDAY", "origin": "MANUAL"}, "ck_place_hours_day_type"),
        ({"day_type": "MON", "origin": "AUTO"}, "ck_place_hours_origin"),
    ],
)
def test_place_hours_check_constraints(database: Database, tmp_path: Path, row: dict[str, str], constraint: str):
    write_samples(tmp_path, "")
    cli.seed_places(database, tmp_path)
    with pytest.raises(IntegrityError) as error, database.transaction() as session:
        session.add(PlaceHourRow(place_id="100", is_closed=False, **row))
    if database.engine.dialect.name == "postgresql":
        assert constraint in str(error.value)


def test_ingestion_run_status_check_constraint(database: Database):
    with database.transaction() as session:
        session.add(IngestionRunRow(source_id="tourapi", started_at=SEEDED_AT, status="RUNNING"))
    with pytest.raises(IntegrityError), database.transaction() as session:
        session.add(IngestionRunRow(source_id="tourapi", started_at=SEEDED_AT, status="DONE"))


def store_hours(database: Database) -> set[str]:
    with database.transaction() as session:
        return set(session.scalars(select(PlaceHourRow.day_type)))


def test_cli_seed_places_requires_database_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", "")
    assert cli.main(["seed-places"]) == 2


def test_cli_seed_places_runs_twice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = Database(f"sqlite:///{tmp_path / 'seed.db'}")
    upgrade(database)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'seed.db'}")

    assert cli.main(["seed-places", "--dir", str(SAMPLE_DIR)]) == 0
    assert cli.main(["seed-places"]) == 0

    assert SqlPlaceStore(database).load() == by_id(load_sample_places().samples())
    database.dispose()
