"""FR-016 TourAPI 관광지 다건 수집 및 결과 집계."""

import os
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass

import httpx

from .public_places import PublicPlaceRecord
from .tourapi_client import TourAPIError, TourAPIRejectedError, TourAPITransportError, fetch_public_place


@dataclass(frozen=True)
class BatchResult:
    records: tuple[PublicPlaceRecord, ...]
    success_count: int
    # 전송 오류(HTTP·네트워크·형식) 건수. 첫 오류에서 멈추므로 0 또는 1 이다.
    transport_failures: int
    # 검증 거절(항목 없음·검증 실패·잘못된 ID) 건수
    rejected: int
    # 실제로 보낸 HTTP 요청 수(호출 한도 집계용)
    call_count: int
    # 첫 전송 오류 메시지. 키·URL 을 담지 않는다.
    error_message: str | None = None
    # should_stop 으로 중간에 멈췄다(남은 ID 는 부르지 않았다).
    interrupted: bool = False

    @property
    def failed_count(self) -> int:
        return self.transport_failures + self.rejected


def collect_public_places(
    content_ids: list[str],
    *,
    api_key: str | None = None,
    client: httpx.Client | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> BatchResult:
    """관광지 ID별로 조회하고 성공·거절·전송 오류 건수를 집계한다. DB 에 쓰지 않는다.

    키가 없으면 호출하지 않고 `TourAPITransportError` 를 낸다.
    전송 오류가 나면 남은 ID 는 부르지 않는다(실행 전체가 실패이므로 호출 한도를 아낀다).
    `should_stop()` 이 참이면 지금 호출을 마친 뒤 멈추고 `interrupted=True` 로 돌려준다.
    """
    key = (api_key or os.getenv("TOURAPI_SERVICE_KEY") or "").strip()
    if not key:
        raise TourAPITransportError("TOURAPI_SERVICE_KEY가 설정되지 않았습니다.")

    records = []
    rejected = transport = calls = 0
    error: str | None = None
    interrupted = False
    # 넘겨받은 client 는 닫지 않는다.
    with httpx.Client(timeout=10.0) if client is None else nullcontext(client) as http:
        for content_id in dict.fromkeys(content_ids):
            if should_stop is not None and should_stop():
                interrupted = True
                break
            if not content_id.isdigit():
                rejected += 1
                continue
            calls += 1
            try:
                records.append(fetch_public_place(content_id, api_key=key, client=http))
            except TourAPIRejectedError:
                rejected += 1
            except TourAPIError as exc:
                transport += 1
                error = str(exc)
                break

    return BatchResult(
        records=tuple(records),
        success_count=len(records),
        transport_failures=transport,
        rejected=rejected,
        call_count=calls,
        error_message=error,
        interrupted=interrupted,
    )
