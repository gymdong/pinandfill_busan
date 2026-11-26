"""FR-016 공공데이터 관광지 수집 결과 검증."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PublicPlaceRecord:
    content_id: str
    name: str
    latitude: float
    longitude: float
    address: str


def parse_public_place(item: Mapping[str, Any]) -> PublicPlaceRecord | None:
    """TourAPI 관광지 항목을 검증하고 표준 형태로 변환한다."""
    content_id = str(item.get("contentid") or "").strip()
    name = str(item.get("title") or "").strip()
    address = str(item.get("addr1") or "").strip()

    if not content_id.isdigit() or not name:
        return None

    try:
        latitude = float(item["mapy"])
        longitude = float(item["mapx"])
    except (KeyError, TypeError, ValueError):
        return None

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None

    return PublicPlaceRecord(
        content_id=content_id,
        name=name,
        latitude=latitude,
        longitude=longitude,
        address=address,
    )


def parse_public_places(
    items: list[Mapping[str, Any]],
) -> tuple[list[PublicPlaceRecord], int]:
    """정상 관광지 목록과 검증 실패 건수를 반환한다."""
    valid_records: list[PublicPlaceRecord] = []
    rejected = 0
    seen_ids: set[str] = set()

    for item in items:
        record = parse_public_place(item)
        if record is None or record.content_id in seen_ids:
            rejected += 1
            continue

        valid_records.append(record)
        seen_ids.add(record.content_id)

    return valid_records, rejected
