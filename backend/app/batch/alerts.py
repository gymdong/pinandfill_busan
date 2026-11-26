"""수집 실패 관리자 알림(FR-016, ERR-005·006).

알림은 구조화 로그 1줄이고, `ADMIN_ALERT_WEBHOOK_URL` 이 있으면 같은 내용을 JSON 으로 POST 한다.
중복 억제는 `ingestion_runs.alerted_at` 으로 판정한다(소스별).
- 실패(FAILED, 한도 SKIPPED): 마지막 SUCCESS 뒤 처음이면 알린다. 이미 알렸으면 마지막 알림 뒤 24시간이 지났을 때만.
- SUCCESS: 마지막 SUCCESS 뒤 알린 실패가 있으면 복구 알림 1회.
웹훅 실패는 경고 로그만 남기고 실행 결과를 바꾸지 않는다. 로그·본문에 URL·키를 넣지 않는다.
"""

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import quiet_http_client_logs
from app.db.models import IngestionRunRow

logger = logging.getLogger(__name__)

ALERT = "ingestion_alert"
RECOVERED = "ingestion_recovered"
REPEAT_AFTER = timedelta(hours=24)
WEBHOOK_TIMEOUT_SECONDS = 5.0


def alert_event(session: Session, run: IngestionRunRow, now: datetime, *, failing: bool) -> str | None:
    """이 실행으로 보낼 알림 종류. 보낼 것이 없으면 None."""
    earlier = (IngestionRunRow.source_id == run.source_id, IngestionRunRow.id != run.id)
    last_success = session.scalar(
        select(IngestionRunRow.started_at)
        .where(*earlier, IngestionRunRow.status == "SUCCESS", IngestionRunRow.started_at <= run.started_at)
        .order_by(IngestionRunRow.started_at.desc())
        .limit(1)
    )
    alerted = select(IngestionRunRow.alerted_at).where(*earlier, IngestionRunRow.alerted_at.is_not(None))
    if last_success is not None:
        alerted = alerted.where(IngestionRunRow.started_at > last_success)
    last_alerted = session.scalar(alerted.order_by(IngestionRunRow.alerted_at.desc()).limit(1))
    if not failing:
        return RECOVERED if last_alerted is not None else None
    if last_alerted is None or now - last_alerted >= REPEAT_AFTER:
        return ALERT
    return None


class AdminAlert:
    def __init__(self, webhook_url: str | None = None, *, client: httpx.Client | None = None) -> None:
        self._webhook_url = webhook_url
        self._client = client
        # httpx 는 INFO 로 요청 URL 전체를 남긴다. 웹훅 URL 은 비밀이므로 이 클래스만 써도 막는다.
        quiet_http_client_logs()

    def send(self, event: str, run: IngestionRunRow) -> None:
        reason = run.error_message or ""
        if event == ALERT:
            logger.error("%s source=%s run_id=%s status=%s reason=%s", event, run.source_id, run.id, run.status, reason)
        else:
            logger.warning("%s source=%s run_id=%s status=%s", event, run.source_id, run.id, run.status)
        if not self._webhook_url:
            return
        body = {
            "event": event,
            "source": run.source_id,
            "run_id": str(run.id),
            "status": run.status,
            "reason": reason,
            "at": run.finished_at.isoformat() if run.finished_at else None,
        }
        try:
            if self._client is None:
                with httpx.Client(timeout=WEBHOOK_TIMEOUT_SECONDS) as client:
                    client.post(self._webhook_url, json=body).raise_for_status()
            else:
                self._client.post(self._webhook_url, json=body, timeout=WEBHOOK_TIMEOUT_SECONDS).raise_for_status()
        except httpx.HTTPError as exc:
            # 예외 문자열에는 URL 이 들어 있으므로 종류만 남긴다.
            logger.warning("%s webhook_failed source=%s error=%s", event, run.source_id, type(exc).__name__)
