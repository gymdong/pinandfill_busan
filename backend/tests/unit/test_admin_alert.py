"""관리자 알림만 따로 써도 httpx 가 웹훅 URL 을 로그에 남기지 않는다(FR-016, NFR-010)."""

import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest

from app.batch.alerts import ALERT, AdminAlert
from app.db.models import IngestionRunRow

WEBHOOK_URL = "https://hooks.example.test/secret-hook-path"


@pytest.fixture
def httpx_logs_unconfigured() -> Iterator[None]:
    """CLI·앱 시작의 로그 설정을 거치지 않은 상태(httpx 로거 기본 수준)."""
    loggers = [logging.getLogger(name) for name in ("httpx", "httpcore")]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.NOTSET)
    yield
    for logger, level in zip(loggers, levels, strict=True):
        logger.setLevel(level)


def test_webhook_url_is_not_logged(httpx_logs_unconfigured: None, caplog: pytest.LogCaptureFixture):
    bodies: list[bytes] = []

    def webhook(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        return httpx.Response(200)

    run = IngestionRunRow(
        id=uuid.uuid4(),
        source_id="tourapi",
        started_at=datetime(2026, 11, 26, tzinfo=UTC),
        finished_at=datetime(2026, 11, 26, tzinfo=UTC),
        status="FAILED",
        error_message="TourAPI 네트워크 요청 실패",
    )
    with caplog.at_level(logging.DEBUG):
        alert = AdminAlert(WEBHOOK_URL, client=httpx.Client(transport=httpx.MockTransport(webhook)))
        alert.send(ALERT, run)

    assert len(bodies) == 1
    assert "ingestion_alert source=tourapi" in caplog.text
    assert "secret-hook-path" not in caplog.text
