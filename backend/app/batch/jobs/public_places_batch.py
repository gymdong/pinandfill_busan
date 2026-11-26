"""FR-016 TourAPI 관광지 다건 수집 및 결과 집계."""

from dataclasses import dataclass

from .public_places import PublicPlaceRecord
from .tourapi_client import TourAPIError, fetch_public_place


@dataclass(frozen=True)
class BatchResult:
    records: tuple[PublicPlaceRecord, ...]
    success_count: int
    failed_count: int


def collect_public_places(
    content_ids: list[str],
) -> BatchResult:
    """관광지 ID별로 조회하고 성공·실패 건수를 집계한다.

    DB 저장 및 정기 실행은 수행하지 않는다.
    """
    records = []
    failures = 0

    for content_id in dict.fromkeys(content_ids):
        try:
            record = fetch_public_place(content_id)
            records.append(record)
        except (TourAPIError, ValueError):
            failures += 1

    return BatchResult(
        records=tuple(records),
        success_count=len(records),
        failed_count=failures,
    )
