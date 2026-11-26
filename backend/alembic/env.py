"""Alembic 실행 환경. 대상 스키마는 app.db.models 의 메타데이터다.

접속 URL 은 `config.attributes["connection"]`(시험에서 주입) → `sqlalchemy.url` 옵션 → DATABASE_URL 순서로 정한다.
"""

from logging.config import fileConfig

from sqlalchemy import Connection, create_engine, pool

from alembic import context
from app.db.models import Base
from app.db.session import DatabaseSettings, database_url

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url") or DatabaseSettings().url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(url=database_url(_url()), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = create_engine(database_url(_url()), poolclass=pool.NullPool)
    with engine.connect() as connection:
        _run(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
