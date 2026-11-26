"""배치 명령(FR-016). backend/ 에서 `uv run python -m app.batch.cli <명령>`.

- `seed-places [--dir data/samples]`: 표본 CSV(places_sample.csv·place_hours.csv)를 places·place_hours 에 넣는다.
  다시 돌려도 결과가 같다. 스키마는 먼저 `alembic upgrade head` 로 만든다. DATABASE_URL 이 필요하다.
  CSV 에 없는 영업시간 행은 `--prune` 일 때만 지운다. CSV 에서 읽지 못한 행의 요일은 지우지 않는다.
- `run --source tourapi`: 소스 하나를 지금 수집한다(주기·백오프 무시, 한도·잠금은 지킨다).
- `run-due`: 주기가 돌아온 소스를 한 번 수집한다.
- `loop [--tick 300]`: tick 초마다 `run-due` 를 한다. SIGTERM·SIGINT 를 받으면 지금 tick 을 마치고 끝낸다.
  compose 의 `batch` 서비스가 이 명령을 돈다.
"""

import argparse
import logging
import signal
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.batch.alerts import AdminAlert
from app.batch.collector import BatchCollector
from app.batch.jobs.tourapi_job import TourAPIPlacesJob
from app.batch.settings import BatchSettings
from app.core.logging import quiet_http_client_logs
from app.db.session import Database, DatabaseSettings
from app.modules.places.db_repository import SeedResult, SqlPlaceStore
from app.modules.places.samples import SAMPLE_DIR, load_sample_places

logger = logging.getLogger(__name__)


def seed_places(database: Database, directory: Path = SAMPLE_DIR, *, prune: bool = False) -> SeedResult:
    # CSV 파서를 그대로 쓴다(따옴표 안 줄바꿈 처리, 빈 값은 비워 둠).
    data = load_sample_places(directory)
    return SqlPlaceStore(database).upsert_seed(
        data.all(), datetime.now(UTC), invalid_hours=data.invalid_hours, prune=prune
    )


def build_collector(database: Database, settings: BatchSettings, stop: threading.Event | None = None) -> BatchCollector:
    # data06·data07 은 U7 에서 잡을 붙인다. 그 전까지 data_sources 에서도 꺼져 있다.
    return BatchCollector(
        database,
        clock=lambda: datetime.now(UTC),
        alert=AdminAlert(settings.webhook_url()),
        sources={"tourapi": TourAPIPlacesJob(settings.tourapi_key())},
        backoff_base=timedelta(minutes=settings.batch_backoff_base_min),
        stop=stop,
    )


def run_loop(run_once: Callable[[], object], tick_seconds: float, stop: threading.Event) -> int:
    """`stop` 이 설정될 때까지 tick 마다 `run_once` 를 부른다. 한 tick 의 오류는 로그만 남기고 계속한다."""
    ticks = 0
    while not stop.is_set():
        try:
            run_once()
        except Exception as exc:
            # 예외 문자열에 URL 이 들어 있을 수 있으므로 종류만 남긴다.
            logger.error("batch_tick_failed error=%s", type(exc).__name__)
        ticks += 1
        stop.wait(tick_seconds)
    return ticks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.batch.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    seed = commands.add_parser("seed-places", help="표본 CSV 를 places·place_hours 에 넣는다")
    seed.add_argument("--dir", type=Path, default=SAMPLE_DIR, help="표본 CSV 디렉터리")
    seed.add_argument("--prune", action="store_true", help="CSV 에 없는 영업시간 행을 지운다")
    run_one = commands.add_parser("run", help="소스 하나를 지금 수집한다")
    run_one.add_argument("--source", required=True, help="data_sources.id (예: tourapi)")
    commands.add_parser("run-due", help="주기가 돌아온 소스를 한 번 수집한다")
    loop = commands.add_parser("loop", help="tick 마다 run-due 를 한다")
    loop.add_argument("--tick", type=float, default=300, help="tick 간격(초)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    quiet_http_client_logs()

    settings = DatabaseSettings()
    url = settings.url()
    if not url:
        logger.error("DATABASE_URL is not set")
        return 2
    database = Database(url, **settings.engine_options())
    try:
        if args.command == "seed-places":
            return _seed(database, args.dir, args.prune)
        # SIGTERM·SIGINT: 지금 호출을 마치고 실행을 쓰기 없이 FAILED('interrupted') 로 끝낸 뒤 종료한다.
        stop = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())
        collector = build_collector(database, BatchSettings(), stop)
        if args.command == "run":
            if args.source not in collector.sources:
                logger.error("unknown source: %s", args.source)
                return 2
            result = collector.run(args.source)
            return 0 if result is None or result.status != "FAILED" else 1
        if args.command == "run-due":
            return 1 if any(run.status == "FAILED" for run in collector.run_due()) else 0
        logger.info("batch_loop started tick=%ss", args.tick)
        ticks = run_loop(collector.run_due, args.tick, stop)
        logger.info("batch_loop stopped ticks=%d", ticks)
        return 0
    finally:
        database.dispose()


def _seed(database: Database, directory: Path, prune: bool) -> int:
    result = seed_places(database, directory, prune=prune)
    logger.info(
        "seed_places places=%d changed=%d kept_invalid=%d kept_unlisted=%d pruned=%d",
        result.places,
        result.changed,
        result.kept_invalid,
        result.kept_unlisted,
        result.pruned,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
