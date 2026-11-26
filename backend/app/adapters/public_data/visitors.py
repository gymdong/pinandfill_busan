"""DATA-06 지역별 방문자수·DATA-07 관광지 집중률 예측 어댑터(FR-008). 한국관광공사, 공공데이터포털.

확인한 것(공공데이터포털 목록 페이지, 2026-11):
- DATA-06 `한국관광공사_빅데이터_지역별 방문자수_GW`(15101972): 기본 주소 B551011/DataLabService,
  요청 serviceKey·MobileOS·MobileApp·startYmd·endYmd·pageNo·numOfRows. 기초 지자체(시군구) 집계 기능이 있다.
- DATA-07 `한국관광공사_관광지 집중률 방문자 추이 예측 정보`(15128555): 기본 주소 B551011/TatsCnctrRateService,
  요청 serviceKey·MobileOS·MobileApp·areaCd·signguCd(필수)·tAtsNm·pageNo·numOfRows·_type. 조회일 기준 향후 30일.

명세 확인 필요(키가 없어 확인하지 못함): 아래 *_OPERATION 경로와 *_FIELDS 응답 필드 이름, 응답 봉투
(response.header.resultCode·response.body.items.item·totalCount, 다른 KTO API 와 같다고 본다).
실제 응답을 받으면 이 상수와 시험 픽스처만 고친다.

오류 구분(TourAPI 클라이언트와 같다): HTTP·네트워크·JSON·봉투·resultCode·쪽 넘침은 `VisitorTransportError` 로
그 실행 전체를 실패시킨다. 항목 하나의 값이 틀리면 그 항목만 건너뛰고 rejected 로 센다.
요청 URL 에 serviceKey 가 있으므로 예외 메시지·로그에 URL·키를 넣지 않는다.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import httpx

from .regions import RegionCodes

BASE_URL = "https://apis.data.go.kr/B551011"
# 명세 확인 필요: 기초 지자체 지역방문자수 기능의 경로 이름
DATA06_OPERATION = "DataLabService/locgoRegnVisitrDDList"
# 명세 확인 필요: 관광지 집중률 목록조회 기능의 경로 이름
DATA07_OPERATION = "TatsCnctrRateService/tatsCnctrRatedList"
# 명세 확인 필요: 응답 항목 필드(시군구 코드, 기준일 YYYYMMDD, 값)
DATA06_FIELDS = {"code": "signguCode", "date": "baseYmd", "value": "touNum"}
DATA07_FIELDS = {"code": "signguCd", "date": "baseYmd", "value": "cnctrRate"}
SUCCESS_CODE = "0000"
APP_NAME = "PinAndFillBusan"


class VisitorTransportError(Exception):
    """응답 전체를 믿을 수 없다. 메시지에 URL·키가 없다."""


@dataclass
class Fetched:
    """(날짜, 구·군 이름) → 값 목록. DATA-06 은 방문자 구분(현지인·외지인·외국인)별, DATA-07 은 관광지별 값이다."""

    values: dict[tuple[date, str], list[float]] = field(default_factory=dict)
    rejected: int = 0

    def add(self, other: "Fetched") -> None:
        for key, items in other.values.items():
            self.values.setdefault(key, []).extend(items)
        self.rejected += other.rejected


def _items(client: httpx.Client, label: str, url: str, params: Mapping[str, str | int], page_size: int) -> list[Any]:
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        payload: Any = response.json()
    except httpx.HTTPStatusError as exc:
        raise VisitorTransportError(f"{label} 요청 실패 (HTTP {exc.response.status_code})") from None
    except httpx.HTTPError:
        raise VisitorTransportError(f"{label} 네트워크 요청 실패") from None
    except ValueError:
        # 키 오류 등은 200 + XML 로 오기도 한다.
        raise VisitorTransportError(f"{label} JSON 처리 실패") from None
    envelope = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(envelope, Mapping):
        raise VisitorTransportError(f"{label} response 형식 오류")
    header = envelope.get("header")
    code = header.get("resultCode") if isinstance(header, Mapping) else None
    if code is not None and str(code) != SUCCESS_CODE:
        raise VisitorTransportError(f"{label} 오류 응답 (resultCode {str(code)[:10]})")
    body = envelope.get("body")
    if not isinstance(body, Mapping):
        raise VisitorTransportError(f"{label} body 형식 오류")
    items = body.get("items")
    # 결과가 없으면 items 가 빈 문자열로 온다.
    if items in ("", None):
        rows: list[Any] = []
    elif isinstance(items, Mapping):
        item = items.get("item")
        rows = item if isinstance(item, list) else [] if item is None else [item]
    else:
        raise VisitorTransportError(f"{label} items 형식 오류")
    try:
        total = int(body.get("totalCount", len(rows)))
    except (TypeError, ValueError):
        raise VisitorTransportError(f"{label} totalCount 형식 오류") from None
    if total > page_size or total > len(rows):
        # 잘린 자료로 평균을 내면 배수가 틀린다. 쪽 크기(PUBLIC_DATA_PAGE_SIZE)를 늘린다.
        raise VisitorTransportError(f"{label} 응답이 한 쪽을 넘습니다 (totalCount {total})")
    return rows


def _value(item: Any, fields: Mapping[str, str]) -> tuple[str, date, float]:
    if not isinstance(item, Mapping):
        raise ValueError("item")
    code = str(item.get(fields["code"], "")).strip()
    day = datetime.strptime(str(item.get(fields["date"], "")).strip(), "%Y%m%d").date()
    value = float(item.get(fields["value"], ""))
    if not code or not math.isfinite(value) or value < 0:
        raise ValueError("value")
    return code, day, value


class _Adapter:
    label = ""

    def __init__(self, api_key: str, regions: RegionCodes, client: httpx.Client, *, page_size: int) -> None:
        self._api_key = api_key
        self._regions = regions
        self._client = client
        self._page_size = page_size

    def _params(self, **extra: str) -> dict[str, str | int]:
        return {
            "serviceKey": self._api_key,
            "MobileOS": "ETC",
            "MobileApp": APP_NAME,
            "_type": "json",
            "pageNo": 1,
            "numOfRows": self._page_size,
            **extra,
        }


class VisitorCountAdapter(_Adapter):
    """DATA-06: 하루치 전국 시군구 방문자수 중 대응표에 있는 부산 구·군만 남긴다. 과거 자료다."""

    label = "DATA-06"

    def fetch_day(self, day: date) -> Fetched:
        ymd = day.strftime("%Y%m%d")
        rows = _items(
            self._client,
            self.label,
            f"{BASE_URL}/{DATA06_OPERATION}",
            self._params(startYmd=ymd, endYmd=ymd),
            self._page_size,
        )
        result = Fetched()
        for item in rows:
            try:
                code, item_day, value = _value(item, DATA06_FIELDS)
                if item_day != day:
                    raise ValueError("date")
            except (TypeError, ValueError):
                result.rejected += 1
                continue
            region = self._regions.data06.get(code)
            if region is not None:
                result.values.setdefault((day, region), []).append(value)
        return result


class ConcentrationForecastAdapter(_Adapter):
    """DATA-07: 구·군 하나의 관광지별 향후 30일 집중률. 응답에 그 구·군 관광지가 없으면 빈 결과다."""

    label = "DATA-07"

    def fetch_region(self, region: str) -> Fetched:
        area_code, signgu_code = self._regions.data07[region]
        rows = _items(
            self._client,
            self.label,
            f"{BASE_URL}/{DATA07_OPERATION}",
            self._params(areaCd=area_code, signguCd=signgu_code),
            self._page_size,
        )
        result = Fetched()
        for item in rows:
            try:
                code, day, value = _value(item, DATA07_FIELDS)
                if code != signgu_code:
                    raise ValueError("region")
            except (TypeError, ValueError):
                result.rejected += 1
                continue
            result.values.setdefault((day, region), []).append(value)
        return result
