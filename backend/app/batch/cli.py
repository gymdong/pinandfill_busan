"""배치 명령(FR-016). backend/ 에서 `uv run python -m app.batch.cli <명령>`.

- `seed-places [--dir data/samples]`: 표본 CSV(places_sample.csv·place_hours.csv)를 places·place_hours 에 넣는다.
  다시 돌려도 결과가 같다. 스키마는 먼저 `alembic upgrade head` 로 만든다. DATABASE_URL 이 필요하다.
"""

import argparse
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from app.db.session import Database, DatabaseSettings
from app.modules.places.db_repository import SqlPlaceStore
from app.modules.places.samples import SAMPLE_DIR, load_sample_places

logger = logging.getLogger(__name__)


def seed_places(database: Database, directory: Path = SAMPLE_DIR) -> int:
    # CSV 파서를 그대로 쓴다(따옴표 안 줄바꿈 처리, 빈 값은 비워 둠).
    places = load_sample_places(directory).samples()
    return SqlPlaceStore(database).upsert_seed(places, datetime.now(UTC))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.batch.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    seed = commands.add_parser("seed-places", help="표본 CSV 를 places·place_hours 에 넣는다")
    seed.add_argument("--dir", type=Path, default=SAMPLE_DIR, help="표본 CSV 디렉터리")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    url = DatabaseSettings().url()
    if not url:
        logger.error("DATABASE_URL is not set")
        return 2
    database = Database(url)
    try:
        count = seed_places(database, args.dir)
    finally:
        database.dispose()
    logger.info("seed_places upserted=%d", count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
