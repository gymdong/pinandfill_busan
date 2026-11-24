"""FR-016 TourAPI 관광지 상세정보 수집 클라이언트."""

import os
from collections.abc import Mapping
from typing import Any

import httpx

from .public_places import PublicPlaceRecord, parse_public_place

TOURAPI_DETAIL_URL = "https://apis.data.go.kr/B551011/KorService2/detailCommon2"


class TourAPIError(Exception):
    """TourAPI 호출 또는 응답 처리 오류."""


def fetch_public_place(
    content_id: str,
    *,
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> PublicPlaceRecord:
    """TourAPI에서 관광지 1건을 가져와 검증한다."""
    if not content_id.isdigit():
        raise ValueError("유효하지 않은 관광지 ID입니다.")

    key = api_key or os.getenv("TOURAPI_SERVICE_KEY")
    if not key:
        raise TourAPIError("TOURAPI_SERVICE_KEY가 설정되지 않았습니다.")

    params = {
        "serviceKey": key,
        "contentId": content_id,
        "MobileOS": "ETC",
        "MobileApp": "PinAndFillBusan",
        "_type": "json",
    }

    try:
        if client is None:
            with httpx.Client(timeout=10.0) as http:
                response = http.get(TOURAPI_DETAIL_URL, params=params)
        else:
            response = client.get(TOURAPI_DETAIL_URL, params=params)

        response.raise_for_status()
        payload: Any = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise TourAPIError("TourAPI 요청 또는 JSON 처리 실패") from exc

    if not isinstance(payload, dict):
        raise TourAPIError("TourAPI 응답 형식이 올바르지 않습니다.")

    body = payload.get("response", {}).get("body", {})
    items = body.get("items", {})

    if not isinstance(items, Mapping):
        raise TourAPIError("TourAPI 관광지 목록 형식이 올바르지 않습니다.")

    item = items.get("item")
    if isinstance(item, list):
        item = item[0] if item else None

    if not isinstance(item, Mapping):
        raise TourAPIError("관광지 상세정보가 없습니다.")

    record = parse_public_place(item)
    if record is None or record.content_id != content_id:
        raise TourAPIError("관광지 데이터 검증에 실패했습니다.")

    return record
