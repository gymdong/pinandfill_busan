"""공공데이터 배치 수집기(FR-016, UC-010, ERR-005·006).

`BatchCollector.run(source_id)` 한 번의 흐름:
1. 소스별 잠금. PostgreSQL 은 `pg_try_advisory_xact_lock`, SQLite 는 프로세스 Lock. 못 잡으면 기록 없이 None.
2. 꺼진 소스는 SKIPPED(알림 없음).
3. 호출 한도: 오늘(KST 0시부터) call_count 합 + 예정 호출 수 > daily_call_limit 이면 SKIPPED + 알림, 호출 0.
4. RUNNING 행을 먼저 커밋하고, DB 트랜잭션 밖에서 외부 호출을 한다.
5. 전송 오류가 있으면 FAILED + 알림, 쓰기 없음(이전 수집본 유지). 아니면 한 트랜잭션에서 쓰기와 SUCCESS 기록.
   검증 거절은 그 항목만 건너뛰고 rejected_count 로 남긴다.

`run_due(now)` 는 켜진 소스 중 주기(KST 달력)가 돌아왔고 백오프 중이 아닌 것만 돌린다.
error_message·로그에는 키·URL 을 넣지 않는다(NFR-010).
"""

import logging
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import DataSourceRow, IngestionRunRow
from app.db.session import Database

from .alerts import AdminAlert, alert_event

logger = logging.getLogger(__name__)

# 한국은 일광절약시간이 없어 고정 오프셋으로 충분하다(tzdata 가 없는 이미지에서도 동작).
KST = timezone(timedelta(hours=9), "KST")
CYCLES = {"MONTH": timedelta(days=30), "DAY": timedelta(days=1), "MINUTE": timedelta(seconds=60)}
DEFAULT_BACKOFF_BASE = timedelta(minutes=15)


@dataclass(frozen=True)
class JobOutcome:
    """외부 호출 결과. `error` 가 있으면 실패이고 `write` 는 부르지 않는다."""

    call_count: int
    rejected_count: int = 0
    error: str | None = None
    # 자료 기준 시각. None 이면 실행 시각을 쓴다.
    as_of: datetime | None = None
    # 수집본을 쓰고 쓴 건수를 돌려준다. 수집기가 연 트랜잭션 안에서 불린다(SUCCESS 기록과 함께 커밋).
    write: Callable[[datetime], int] | None = None


class SourceJob(Protocol):
    def planned_calls(self, database: Database) -> int:
        """이번 실행에서 보낼 최대 호출 수(한도 검사용)."""
        ...

    def collect(self, database: Database) -> JobOutcome:
        """외부에서 가져온다. DB·파일에 쓰지 않는다(쓰기는 `JobOutcome.write`)."""
        ...


def kst_day_start(now: datetime) -> datetime:
    local = now.astimezone(KST)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def is_due(cycle: str, last_success: datetime | None, now: datetime) -> bool:
    if last_success is None:
        return True
    last, current = last_success.astimezone(KST), now.astimezone(KST)
    if cycle == "MONTH":
        return (last.year, last.month) != (current.year, current.month)
    if cycle == "DAY":
        return last.date() != current.date()
    return now - last_success >= CYCLES["MINUTE"]


def backoff_until(cycle: str, failures: int, last_failure: datetime, base: timedelta) -> datetime:
    wait = min(base * 2 ** min(failures - 1, 20), CYCLES[cycle])
    return last_failure + wait


class BatchCollector:
    def __init__(
        self,
        database: Database,
        *,
        clock: Callable[[], datetime],
        alert: AdminAlert,
        sources: Mapping[str, SourceJob],
        backoff_base: timedelta = DEFAULT_BACKOFF_BASE,
    ) -> None:
        self.database = database
        self.clock = clock
        self.alert = alert
        self.sources = sources
        self.backoff_base = backoff_base
        self._locks = {source_id: threading.Lock() for source_id in sources}

    @contextmanager
    def _source_lock(self, source_id: str) -> Iterator[bool]:
        if self.database.engine.dialect.name == "postgresql":
            # 잠금은 이 연결의 트랜잭션이 끝날 때 풀린다(프로세스가 죽어도 남지 않는다).
            with self.database.engine.connect() as connection, connection.begin():
                acquired = connection.execute(
                    text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"), {"key": f"ingest:{source_id}"}
                ).scalar_one()
                yield bool(acquired)
            return
        lock = self._locks[source_id]
        acquired = lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()

    def run(self, source_id: str) -> IngestionRunRow | None:
        """소스 하나를 지금 돌린다(주기·백오프 무시). 다른 실행이 잠금을 잡고 있으면 기록 없이 None."""
        job = self.sources.get(source_id)
        if job is None:
            raise KeyError(f"unknown source: {source_id}")
        with self._source_lock(source_id) as acquired:
            if not acquired:
                logger.info("ingestion_locked source=%s", source_id)
                return None
            return self._run_locked(source_id, job)

    def _run_locked(self, source_id: str, job: SourceJob) -> IngestionRunRow:
        started = self.clock()
        with self.database.transaction() as session:
            source = session.get(DataSourceRow, source_id)
            if source is None:
                raise KeyError(f"source not in data_sources: {source_id}")
            if not source.enabled:
                logger.info("ingestion_skipped source=%s reason=disabled", source_id)
                return self._finish(session, self._start(session, source_id, started), "SKIPPED", "source disabled")
            planned = job.planned_calls(self.database)
            used = self._calls_today(session, source_id, started)
            limit = source.daily_call_limit
            run = self._start(session, source_id, started)
            over_limit = limit is not None and used + planned > limit
            if over_limit:
                self._finish(session, run, "SKIPPED", f"daily call limit: used={used} planned={planned} limit={limit}")
            else:
                # 실행 중 프로세스가 죽어도 한도 집계에서 빠지지 않게 예정 호출 수를 먼저 적는다.
                run.call_count = planned
        if over_limit:
            self._notify(run, failing=True)
            return run

        try:
            outcome = job.collect(self.database)
        except Exception as exc:
            # 예외 문자열에 URL·키가 들어 있을 수 있으므로 종류만 남긴다.
            outcome = JobOutcome(call_count=planned, error=f"unexpected error: {type(exc).__name__}")
        except BaseException:
            with self.database.transaction() as session:
                self._finish(session, session.merge(run), "FAILED", "interrupted")
            raise

        error = outcome.error if outcome.write is not None else outcome.error or "no result"
        if error is None and outcome.write is not None:
            try:
                # 쓰기와 SUCCESS 기록을 한 트랜잭션으로 커밋한다. 쓰기가 실패하면 함께 롤백된다.
                with self.database.transaction() as session:
                    success = session.merge(run)
                    at = self.clock()
                    success.record_count = outcome.write(at)
                    success.as_of = outcome.as_of or at
                    success.call_count = outcome.call_count
                    success.rejected_count = outcome.rejected_count
                    self._finish(session, success, "SUCCESS", None)
                run = success
            except Exception as exc:
                error = f"write failed: {type(exc).__name__}"
        failing = error is not None
        if failing:
            with self.database.transaction() as session:
                run = session.merge(run)
                run.call_count = outcome.call_count
                run.rejected_count = outcome.rejected_count
                self._finish(session, run, "FAILED", error)
        logger.info(
            "ingestion_finished source=%s run_id=%s status=%s records=%s rejected=%s calls=%s",
            source_id,
            run.id,
            run.status,
            run.record_count,
            run.rejected_count,
            run.call_count,
        )
        self._notify(run, failing=failing)
        return run

    def _start(self, session: Session, source_id: str, started: datetime) -> IngestionRunRow:
        run = IngestionRunRow(source_id=source_id, started_at=started, status="RUNNING")
        session.add(run)
        session.flush()
        return run

    def _finish(self, session: Session, run: IngestionRunRow, status: str, error: str | None) -> IngestionRunRow:
        run.status = status
        run.error_message = error
        run.finished_at = self.clock()
        if run.call_count is None:
            run.call_count = 0
        session.flush()
        return run

    def _calls_today(self, session: Session, source_id: str, now: datetime) -> int:
        total = session.scalar(
            select(func.coalesce(func.sum(IngestionRunRow.call_count), 0)).where(
                IngestionRunRow.source_id == source_id, IngestionRunRow.started_at >= kst_day_start(now)
            )
        )
        return int(total or 0)

    def _notify(self, run: IngestionRunRow, *, failing: bool) -> None:
        now = self.clock()
        with self.database.transaction() as session:
            event = alert_event(session, run, now, failing=failing)
        if event is None:
            return
        self.alert.send(event, run)
        run.alerted_at = now
        with self.database.transaction() as session:
            session.merge(run)

    def due_sources(self, now: datetime) -> list[str]:
        """켜져 있고 주기가 돌아왔으며 백오프 중이 아닌 소스(등록된 것만)."""
        due = []
        with self.database.transaction() as session:
            sources = session.scalars(select(DataSourceRow).where(DataSourceRow.enabled).order_by(DataSourceRow.id))
            for source in sources:
                if source.id not in self.sources:
                    logger.warning("ingestion_unregistered source=%s", source.id)
                    continue
                if source.refresh_cycle not in CYCLES:
                    logger.warning("ingestion_unknown_cycle source=%s cycle=%s", source.id, source.refresh_cycle)
                    continue
                runs = IngestionRunRow.source_id == source.id
                last_success = session.scalar(
                    select(func.max(IngestionRunRow.started_at)).where(runs, IngestionRunRow.status == "SUCCESS")
                )
                if not is_due(source.refresh_cycle, last_success, now):
                    continue
                # 마지막 성공 뒤의 FAILED·SKIPPED(한도) 를 연속 실패로 센다.
                failed = select(func.count(), func.max(IngestionRunRow.started_at)).where(
                    runs, IngestionRunRow.status.in_(("FAILED", "SKIPPED"))
                )
                if last_success is not None:
                    failed = failed.where(IngestionRunRow.started_at > last_success)
                failures, last_failure = session.execute(failed).one()
                if failures and now < backoff_until(source.refresh_cycle, failures, last_failure, self.backoff_base):
                    continue
                due.append(source.id)
        return due

    def run_due(self) -> list[IngestionRunRow]:
        results = []
        for source_id in self.due_sources(self.clock()):
            run = self.run(source_id)
            if run is not None:
                results.append(run)
        return results
