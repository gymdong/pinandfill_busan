"""FR-016 TourAPI 관광지 상세정보 수집 클라이언트."""

import logging
import os
from collections.abc import Mapping
from typing import Any

import httpx

from .public_places import PublicPlaceRecord, parse_public_place

# httpx 는 INFO 로 요청 URL 전체를 남기는데 TourAPI 는 serviceKey 를 쿼리로 보낸다. 키가 로그에 남지 않게 한다.
logging.getLogger("httpx").setLevel(logging.WARNING)

TOURAPI_DETAIL_URL = "https://apis.data.go.kr/B551011/KorService2/detailCommon2"


class TourAPIError(Exception):
    """TourAPI 호출 또는 응답 처리 오류."""


class TourAPITransportError(TourAPIError):
    """키 없음·HTTP·네트워크·JSON·응답 틀(envelope·body·items) 오류. 배치는 이 오류가 1건이라도 나면 쓰지 않는다."""


class TourAPIRejectedError(TourAPIError):
    """응답은 받았으나 항목이 없거나 검증에 실패했다. 배치는 그 장소만 건너뛰고 기존 값을 둔다."""


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
        raise TourAPITransportError("TOURAPI_SERVICE_KEY가 설정되지 않았습니다.")

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
    except httpx.HTTPStatusError as exc:
        raise TourAPITransportError(f"TourAPI 요청 실패 (HTTP {exc.response.status_code})") from None
    except httpx.HTTPError:
        raise TourAPITransportError("TourAPI 네트워크 요청 실패") from None
    except ValueError:
        raise TourAPITransportError("TourAPI JSON 처리 실패") from None

    if not isinstance(payload, dict):
        raise TourAPITransportError("TourAPI 응답 형식이 올바르지 않습니다.")

    envelope = payload.get("response")
    if not isinstance(envelope, Mapping):
        raise TourAPITransportError("TourAPI response 형식 오류")

    body = envelope.get("body")
    if not isinstance(body, Mapping):
        raise TourAPITransportError("TourAPI body 형식 오류")

    items = body.get("items")

    if not isinstance(items, Mapping):
        raise TourAPITransportError("TourAPI 관광지 목록 형식이 올바르지 않습니다.")

    item = items.get("item")
    if isinstance(item, list):
        item = item[0] if item else None

    if not isinstance(item, Mapping):
        raise TourAPIRejectedError("관광지 상세정보가 없습니다.")

    record = parse_public_place(item)
    if record is None or record.content_id != content_id:
        raise TourAPIRejectedError("관광지 데이터 검증에 실패했습니다.")

    return record
