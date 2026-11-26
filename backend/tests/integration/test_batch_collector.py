"""FR-016 배치 수집기: 기록·이전 수집본 유지·호출 한도·주기·백오프·알림·잠금.

SQLite(alembic)는 항상, PostgreSQL 은 TEST_DATABASE_URL 이 있을 때 돈다. TourAPI·웹훅은 httpx MockTransport 다.
응답은 시험용으로 직접 만든 형식이다(실제 TourAPI 응답 복사가 아니다).
"""

import json
import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text

from app.batch.alerts import AdminAlert
from app.batch.cli import run_loop
from app.batch.collector import KST, BatchCollector, is_due
from app.batch.jobs.tourapi_job import TourAPIPlacesJob
from app.db.models import DataSourceRow, IngestionRunRow, PlaceHourRow, PlaceRow
from app.db.session import Database
from app.modules.places.db_repository import SqlPlaceStore
from app.modules.places.samples import load_sample_places
from tests.integration.test_db_persistence import DB_KINDS, open_database, upgrade

SECRET_KEY = "SECRET_TOURAPI_KEY_93f1"
WEBHOOK_URL = "https://hooks.example.test/secret-hook-path"
SEEDED_AT = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
# 2026-11-26 10:00 KST
T0 = datetime(2026, 11, 26, 1, 0, tzinfo=UTC)


@dataclass
class FakeTourAPI:
    """contentId 별 응답을 바꿀 수 있는 TourAPI 목. failures: id → '500' | 'timeout' | 'reject'."""

    failures: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    # (들어옴, 풀림): 있으면 첫 응답 전에 들어옴을 알리고 풀릴 때까지 기다린다.
    gate: tuple[threading.Event, threading.Event] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.gate is not None:
            entered, release = self.gate
            entered.set()
            assert release.wait(10)
        content_id = request.url.params["contentId"]
        self.calls.append(content_id)
        failure = self.failures.get(content_id)
        if failure == "500":
            return httpx.Response(500, json={})
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        returned_id = "999999" if failure == "reject" else content_id
        item = {
            "contentid": returned_id,
            "title": f"수집 {content_id}",
            "addr1": f"부산광역시 수집주소 {content_id}",
            "mapy": "35.1",
            "mapx": "129.1",
        }
        return httpx.Response(200, json={"response": {"body": {"items": {"item": item}}}})


@dataclass
class Clock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Harness:
    database: Database
    api: FakeTourAPI
    clock: Clock
    webhook_bodies: list[dict[str, Any]]
    collector: BatchCollector


@pytest.fixture(params=DB_KINDS)
def database(request: pytest.FixtureRequest) -> Iterator[Database]:
    database = open_database(request.param)
    upgrade(database)
    SqlPlaceStore(database).upsert_seed(load_sample_places().all(), SEEDED_AT)
    yield database
    database.dispose()


def make_harness(database: Database, *, api_key: str | None = SECRET_KEY, webhook_status: int = 200) -> Harness:
    api = FakeTourAPI()
    clock = Clock(T0)
    bodies: list[dict[str, Any]] = []

    def webhook(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(webhook_status)

    collector = BatchCollector(
        database,
        clock=clock,
        alert=AdminAlert(WEBHOOK_URL, client=httpx.Client(transport=httpx.MockTransport(webhook))),
        sources={"tourapi": TourAPIPlacesJob(api_key, client=httpx.Client(transport=httpx.MockTransport(api.handler)))},
    )
    return Harness(database, api, clock, bodies, collector)


@pytest.fixture
def harness(database: Database) -> Harness:
    return make_harness(database)


def place_rows(database: Database) -> list[tuple[Any, ...]]:
    with database.transaction() as session:
        places = [
            (row.id, row.name, row.lat, row.lng, row.address, row.ref_date, row.source_org, row.collected_at)
            for row in session.scalars(select(PlaceRow).order_by(PlaceRow.id))
        ]
        hours = [
            (row.place_id, row.day_type, row.open_time, row.close_time, row.is_closed, row.origin)
            for row in session.scalars(select(PlaceHourRow).order_by(PlaceHourRow.place_id, PlaceHourRow.day_type))
        ]
    return [*places, *hours]


def runs(database: Database) -> list[IngestionRunRow]:
    with database.transaction() as session:
        return list(session.scalars(select(IngestionRunRow).order_by(IngestionRunRow.started_at)))


def set_source(database: Database, **values: Any) -> None:
    with database.transaction() as session:
        source = session.get(DataSourceRow, "tourapi")
        assert source is not None
        for name, value in values.items():
            setattr(source, name, value)


def alert_lines(caplog: pytest.LogCaptureFixture, event: str = "ingestion_alert") -> list[str]:
    return [record.getMessage() for record in caplog.records if record.getMessage().startswith(f"{event} ")]


def assert_no_secret(caplog: pytest.LogCaptureFixture, h: Harness) -> None:
    # A2-9: 로그·error_message·웹훅 본문에 키·웹훅 URL 이 없다.
    texts = [caplog.text, json.dumps(h.webhook_bodies, ensure_ascii=False)]
    texts += [run.error_message or "" for run in runs(h.database)]
    for value in texts:
        assert SECRET_KEY not in value
        assert "serviceKey" not in value
        assert "secret-hook-path" not in value


def test_success_updates_places_and_records_run(harness: Harness, caplog: pytest.LogCaptureFixture):
    ids = SqlPlaceStore(harness.database).public_ids()
    before = {item.place.id: item for item in SqlPlaceStore(harness.database).load()}
    with caplog.at_level(logging.INFO):
        run = harness.collector.run("tourapi")

    # A2-3
    assert run is not None and run.status == "SUCCESS"
    assert (run.record_count, run.rejected_count, run.call_count) == (len(ids), 0, len(ids))
    assert run.as_of == T0 and run.finished_at == T0 and run.error_message is None
    assert sorted(harness.api.calls) == sorted(ids)
    after = {item.place.id: item for item in SqlPlaceStore(harness.database).load()}
    for place_id, item in after.items():
        assert item.place.name == f"수집 {place_id}"
        assert (item.place.lat, item.place.lng) == (35.1, 129.1)
        # A2-10: 수동 값은 그대로다.
        old = before[place_id]
        assert (item.ref_date, item.source_org, item.hours, item.hours_origin, item.place.category) == (
            old.ref_date,
            old.source_org,
            old.hours,
            old.hours_origin,
            old.place.category,
        )
    with harness.database.transaction() as session:
        assert {row.collected_at for row in session.scalars(select(PlaceRow))} == {T0}
    # 첫 성공은 알리지 않는다.
    assert not alert_lines(caplog) and not alert_lines(caplog, "ingestion_recovered") and not harness.webhook_bodies
    assert_no_secret(caplog, harness)


@pytest.mark.parametrize("failure", ["500", "timeout"])
def test_transport_failure_keeps_previous_snapshot(harness: Harness, caplog: pytest.LogCaptureFixture, failure: str):
    harness.collector.run("tourapi")
    snapshot = place_rows(harness.database)
    harness.clock.now = T0 + timedelta(days=40)
    ids = SqlPlaceStore(harness.database).public_ids()
    # 한 곳만 실패하면 나머지가 성공해도 아무것도 쓰지 않는다(A2-4).
    harness.api.failures[ids[-1]] = failure
    harness.api.failures[ids[0]] = "reject"
    harness.api.calls.clear()
    with caplog.at_level(logging.INFO):
        run = harness.collector.run("tourapi")

    assert run is not None and run.status == "FAILED"
    assert run.record_count is None and run.as_of is None
    assert run.error_message in ("TourAPI 요청 실패 (HTTP 500)", "TourAPI 네트워크 요청 실패")
    assert run.call_count == len(harness.api.calls) == len(ids)
    assert place_rows(harness.database) == snapshot
    assert len(alert_lines(caplog)) == 1
    assert len(harness.webhook_bodies) == 1
    body = harness.webhook_bodies[0]
    assert (body["event"], body["source"], body["status"], body["run_id"]) == (
        "ingestion_alert",
        "tourapi",
        "FAILED",
        str(run.id),
    )
    assert runs(harness.database)[-1].alerted_at == harness.clock.now
    assert_no_secret(caplog, harness)


def test_write_error_rolls_back_and_records_failure(harness: Harness, monkeypatch: pytest.MonkeyPatch):
    snapshot = place_rows(harness.database)
    real_update = SqlPlaceStore.update_collected

    def update_then_fail(self: SqlPlaceStore, records: Any, at: datetime) -> int:
        real_update(self, records, at)
        raise RuntimeError("disk full")

    monkeypatch.setattr(SqlPlaceStore, "update_collected", update_then_fail)
    run = harness.collector.run("tourapi")

    assert run is not None and (run.status, run.error_message) == ("FAILED", "write failed: RuntimeError")
    assert place_rows(harness.database) == snapshot
    assert [row.status for row in runs(harness.database)] == ["FAILED"]


def test_missing_key_fails_without_calls(database: Database, caplog: pytest.LogCaptureFixture):
    h = make_harness(database, api_key=None)
    snapshot = place_rows(database)
    with caplog.at_level(logging.INFO):
        run = h.collector.run("tourapi")

    # A2-5
    assert run is not None and run.status == "FAILED"
    assert run.error_message == "TOURAPI_SERVICE_KEY가 설정되지 않았습니다."
    assert run.call_count == 0 and h.api.calls == []
    assert place_rows(database) == snapshot
    assert len(alert_lines(caplog)) == 1


def test_rejected_only_is_success_with_count(harness: Harness):
    ids = SqlPlaceStore(harness.database).public_ids()
    harness.api.failures[ids[0]] = "reject"
    before = place_rows(harness.database)
    run = harness.collector.run("tourapi")

    assert run is not None and run.status == "SUCCESS"
    assert (run.record_count, run.rejected_count, run.call_count) == (len(ids) - 1, 1, len(ids))
    # 거절된 장소는 기존 행 그대로다.
    rejected_before = next(row for row in before if row[0] == ids[0])
    assert next(row for row in place_rows(harness.database) if row[0] == ids[0]) == rejected_before


def test_daily_call_limit_counts_per_kst_day(harness: Harness, caplog: pytest.LogCaptureFixture):
    count = len(SqlPlaceStore(harness.database).public_ids())
    set_source(harness.database, daily_call_limit=count * 2 - 1)
    # 2026-11-26 23:50 KST
    harness.clock.now = datetime(2026, 11, 26, 14, 50, tzinfo=UTC)
    assert harness.collector.run("tourapi").status == "SUCCESS"  # type: ignore[union-attr]
    harness.api.calls.clear()

    # 23:59:59 KST: 같은 날이라 한도를 넘는다(A2-6).
    harness.clock.now = datetime(2026, 11, 26, 14, 59, 59, tzinfo=UTC)
    with caplog.at_level(logging.INFO):
        limited = harness.collector.run("tourapi")
    assert limited is not None and limited.status == "SKIPPED"
    assert limited.call_count == 0 and harness.api.calls == []
    assert limited.error_message == f"daily call limit: used={count} planned={count} limit={count * 2 - 1}"
    assert len(alert_lines(caplog)) == 1 and len(harness.webhook_bodies) == 1

    # 00:00 KST: 새 날이라 다시 돈다. 앞의 알림이 있었으므로 복구 알림 1회.
    harness.clock.now = datetime(2026, 11, 26, 15, 0, tzinfo=UTC)
    with caplog.at_level(logging.INFO):
        run = harness.collector.run("tourapi")
    assert run is not None and run.status == "SUCCESS"
    assert len(harness.api.calls) == count
    assert len(alert_lines(caplog, "ingestion_recovered")) == 1
    assert [body["event"] for body in harness.webhook_bodies] == ["ingestion_alert", "ingestion_recovered"]


def test_disabled_source_is_skipped_without_calls_or_alert(harness: Harness, caplog: pytest.LogCaptureFixture):
    set_source(harness.database, enabled=False)
    with caplog.at_level(logging.INFO):
        run = harness.collector.run("tourapi")
    assert run is not None and (run.status, run.error_message, run.call_count) == ("SKIPPED", "source disabled", 0)
    assert harness.api.calls == [] and not alert_lines(caplog) and not harness.webhook_bodies
    assert harness.collector.due_sources(T0) == []


def test_month_cycle_uses_kst_calendar(harness: Harness):
    # 2026-11-30 23:59 KST 성공
    harness.clock.now = datetime(2026, 11, 30, 14, 59, tzinfo=UTC)
    assert [run.status for run in harness.collector.run_due()] == ["SUCCESS"]
    # UTC 로는 12월이 아니어도 KST 로는 12월 1일 00:00 이다.
    assert harness.collector.due_sources(datetime(2026, 11, 30, 14, 59, 59, tzinfo=UTC)) == []
    assert harness.collector.due_sources(datetime(2026, 11, 30, 15, 0, tzinfo=UTC)) == ["tourapi"]


def test_is_due_day_and_minute_cycles():
    last = datetime(2026, 11, 26, 14, 59, tzinfo=UTC)  # 23:59 KST
    assert not is_due("DAY", last, datetime(2026, 11, 26, 14, 59, 59, tzinfo=UTC))
    assert is_due("DAY", last, datetime(2026, 11, 26, 15, 0, tzinfo=UTC))
    assert not is_due("MINUTE", last, last + timedelta(seconds=59))
    assert is_due("MINUTE", last, last + timedelta(seconds=60))
    assert is_due("MONTH", None, last)
    assert datetime(2026, 11, 26, 15, 0, tzinfo=UTC).astimezone(KST).day == 27


def test_backoff_and_alert_dedup(harness: Harness, caplog: pytest.LogCaptureFixture):
    ids = SqlPlaceStore(harness.database).public_ids()
    harness.api.failures[ids[0]] = "500"
    clock = harness.clock

    def tick(at: datetime) -> list[str]:
        clock.now = at
        return [run.status for run in harness.collector.run_due()]

    with caplog.at_level(logging.INFO):
        assert tick(T0) == ["FAILED"]
        # 연속 1회: 15분 백오프
        assert tick(T0 + timedelta(minutes=14)) == []
        assert tick(T0 + timedelta(minutes=15)) == ["FAILED"]
        # 연속 2회: 마지막 실패 + 30분
        assert tick(T0 + timedelta(minutes=44)) == []
        assert tick(T0 + timedelta(minutes=45)) == ["FAILED"]
        # 연속 실패 3회에 알림은 1회(A2-7).
        assert len(alert_lines(caplog)) == 1 and len(harness.webhook_bodies) == 1

        # 24시간이 지나면 계속 실패 중임을 다시 알린다.
        assert tick(T0 + timedelta(hours=24)) == ["FAILED"]
        assert len(alert_lines(caplog)) == 2

        # 복구 알림 1회, 그 뒤 이번 달에는 더 돌지 않는다.
        harness.api.failures.clear()
        assert tick(T0 + timedelta(hours=27)) == ["SUCCESS"]
        assert len(alert_lines(caplog, "ingestion_recovered")) == 1
        assert tick(T0 + timedelta(hours=30)) == []
    assert [body["event"] for body in harness.webhook_bodies] == [
        "ingestion_alert",
        "ingestion_alert",
        "ingestion_recovered",
    ]
    assert_no_secret(caplog, harness)


def test_backoff_is_capped_by_cycle():
    from app.batch.collector import backoff_until

    assert backoff_until("MINUTE", 30, T0, timedelta(minutes=15)) == T0 + timedelta(seconds=60)
    assert backoff_until("MONTH", 500, T0, timedelta(minutes=15)) == T0 + timedelta(days=30)


def test_webhook_failure_does_not_change_result(database: Database, caplog: pytest.LogCaptureFixture):
    h = make_harness(database, webhook_status=503)
    h.api.failures[SqlPlaceStore(database).public_ids()[0]] = "500"
    with caplog.at_level(logging.INFO):
        run = h.collector.run("tourapi")
    assert run is not None and run.status == "FAILED"
    assert any("webhook_failed" in record.getMessage() for record in caplog.records)
    assert WEBHOOK_URL not in caplog.text


def test_concurrent_run_is_skipped_without_record(harness: Harness, database: Database):
    if database.engine.dialect.name == "postgresql":
        # 다른 프로세스가 같은 소스 잠금을 잡고 있는 상태.
        with database.engine.connect() as other, other.begin():
            assert other.execute(text("SELECT pg_try_advisory_xact_lock(hashtext('ingest:tourapi'))")).scalar_one()
            assert harness.collector.run("tourapi") is None
    else:
        lock = harness.collector._locks["tourapi"]
        with lock:
            assert harness.collector.run("tourapi") is None
    assert runs(database) == [] and harness.api.calls == []
    # 잠금이 풀리면 다시 돈다.
    assert harness.collector.run("tourapi").status == "SUCCESS"  # type: ignore[union-attr]


def test_two_collectors_race_on_postgres(database: Database):
    if database.engine.dialect.name != "postgresql":
        pytest.skip("advisory lock 은 PostgreSQL 전용이다")
    first, second = make_harness(database), make_harness(database)
    entered, release = threading.Event(), threading.Event()
    first.api.gate = (entered, release)
    results: list[IngestionRunRow | None] = []
    worker = threading.Thread(target=lambda: results.append(first.collector.run("tourapi")))
    worker.start()
    try:
        assert entered.wait(10)
        # 다른 수집기(다른 프로세스와 같다)는 잠금을 못 잡고 기록 없이 끝난다.
        assert second.collector.run("tourapi") is None
        assert second.api.calls == []
    finally:
        release.set()
        worker.join(10)
    assert results and results[0] is not None and results[0].status == "SUCCESS"
    assert [run.status for run in runs(database)] == ["SUCCESS"]


def test_loop_runs_ticks_until_stopped():
    stop = threading.Event()
    calls: list[int] = []

    def once() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("tick 오류는 루프를 멈추지 않는다")
        if len(calls) == 2:
            stop.set()

    assert run_loop(once, 0, stop) == 2
    assert len(calls) == 2
