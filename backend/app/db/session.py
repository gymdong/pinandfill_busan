"""DB 연결과 트랜잭션 경계(SQLAlchemy 2.x, 운영은 PostgreSQL).

`DATABASE_URL` 이 비어 있으면 DB 를 쓰지 않는다. 앱은 메모리 저장소로 돈다(테스트·로컬 기본).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[2]


class DatabaseSettings(BaseSettings):
    """환경변수 `DATABASE_URL` 또는 backend/.env 에서 읽는다. 값(비밀번호 포함)은 로그·오류에 내지 않는다."""

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr | None = None

    def url(self) -> str | None:
        value = self.database_url.get_secret_value().strip() if self.database_url else ""
        return value or None


def database_url(raw: str) -> URL:
    """`postgresql://` 는 psycopg 3 드라이버로 연다(SQLAlchemy 기본값은 설치하지 않은 psycopg2)."""
    url = make_url(raw)
    if url.drivername in ("postgresql", "postgres"):
        url = url.set(drivername="postgresql+psycopg")
    return url


class Database:
    """엔진·세션 팩토리와 현재 트랜잭션.

    `transaction()` 은 다시 들어가도 바깥 트랜잭션을 그대로 쓴다. 그래서 서비스가 편집 한 번을
    `transaction()` 으로 감싸면 그 안의 저장소 호출(일정 저장·스냅샷 기록)이 한 트랜잭션으로 커밋되고,
    예외가 나면 함께 롤백된다. 서비스 밖에서 저장소를 직접 부르면 호출마다 짧은 트랜잭션을 연다.
    """

    def __init__(self, url: str | URL, **engine_options: Any) -> None:
        url = database_url(url) if isinstance(url, str) else url
        if url.get_backend_name() == "sqlite":
            # 시험용. pysqlite 의 예전 트랜잭션 처리는 SAVEPOINT 를 바깥 트랜잭션 밖에서 커밋한다.
            engine_options["connect_args"] = {"autocommit": False, **engine_options.get("connect_args", {})}
        self.engine = create_engine(url, pool_pre_ping=True, **engine_options)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)
        self._current: ContextVar[Session | None] = ContextVar("pinandfill_db_session", default=None)

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        current = self._current.get()
        if current is not None:
            yield current
            return
        with self._sessions() as session, session.begin():
            token = self._current.set(session)
            try:
                yield session
            finally:
                self._current.reset(token)

    def in_transaction(self) -> bool:
        return self._current.get() is not None

    def dispose(self) -> None:
        self.engine.dispose()
