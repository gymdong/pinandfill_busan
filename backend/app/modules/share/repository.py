"""공유 링크 저장소(FR-011, SDD shared_links). 토큰 원문은 저장하지 않고 SHA-256 해시만 저장한다.

DB 가 유출돼도 저장된 값으로는 링크를 만들 수 없다. 원문 토큰은 만들 때 한 번만 응답으로 돌려준다.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Protocol

from sqlalchemy import select

from app.db.models import SharedLinkRow
from app.db.session import Database


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SharedLink:
    trip_id: str
    expires_at: datetime | None


class ShareLinkRepository(Protocol):
    def create(self, trip_id: str, digest: str, expires_at: datetime | None) -> None: ...

    def find(self, digest: str) -> SharedLink | None: ...


class InMemoryShareLinks:
    """메모리 저장소. 프로세스가 재시작되면 링크가 사라진다(여행도 함께 사라진다)."""

    def __init__(self) -> None:
        self._links: dict[str, SharedLink] = {}
        self._lock = Lock()

    def create(self, trip_id: str, digest: str, expires_at: datetime | None) -> None:
        with self._lock:
            self._links[digest] = SharedLink(trip_id, expires_at)

    def find(self, digest: str) -> SharedLink | None:
        with self._lock:
            return self._links.get(digest)


class SqlShareLinks:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, trip_id: str, digest: str, expires_at: datetime | None) -> None:
        with self.database.transaction() as session:
            session.add(SharedLinkRow(trip_id=uuid.UUID(trip_id), token=digest, expires_at=expires_at))

    def find(self, digest: str) -> SharedLink | None:
        with self.database.transaction(snapshot=True) as session:
            row = session.scalars(select(SharedLinkRow).where(SharedLinkRow.token == digest)).first()
            return None if row is None else SharedLink(str(row.trip_id), row.expires_at)
