"""DATA-06·07 어댑터 계약(httpx MockTransport).

응답·코드는 시험용으로 직접 만든 가짜(TEST FIXTURE)다. 실제 API 응답 복사가 아니고,
코드 `F…` 는 실제 시군구 코드가 아니다.
"""

from datetime import date
from typing import Any

import httpx
import pytest

from app.adapters.public_data.regions import BUSAN_DISTRICTS, RegionCodeError, RegionCodes, load_region_codes
from app.adapters.public_data.visitors import (
    DATA06_OPERATION,
    DATA07_OPERATION,
    ConcentrationForecastAdapter,
    VisitorCountAdapter,
    VisitorTransportError,
)

FAKE_KEY = "FAKE_DATA_KEY_7c1d"
# 가짜 코드(실제 시군구 코드 아님)
REGIONS = RegionCodes(
    data06={"F06-YD": "영도구", "F06-HU": "해운대구"},
    data07={"영도구": ("FA", "F07-YD")},
)


def envelope(items: list[dict[str, Any]] | str, total: int | None = None, code: str = "0000") -> dict[str, Any]:
    body_items: Any = items if isinstance(items, str) else {"item": items}
    count = total if total is not None else (0 if isinstance(items, str) else len(items))
    return {
        "response": {
            "header": {"resultCode": code, "resultMsg": "OK"},
            "body": {"items": body_items, "numOfRows": 1000, "pageNo": 1, "totalCount": count},
        }
    }


def client_for(response: httpx.Response | Exception, seen: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if isinstance(response, Exception):
            raise response
        return response

    return httpx.Client(transport=httpx.MockTransport(handler))


def data06(response: httpx.Response | Exception, seen: list[httpx.Request] | None = None) -> VisitorCountAdapter:
    return VisitorCountAdapter(
        FAKE_KEY, REGIONS, client_for(response, seen if seen is not None else []), page_size=1000
    )


def data07(
    response: httpx.Response | Exception, seen: list[httpx.Request] | None = None
) -> ConcentrationForecastAdapter:
    return ConcentrationForecastAdapter(
        FAKE_KEY, REGIONS, client_for(response, seen if seen is not None else []), page_size=1000
    )


def test_data06_maps_codes_to_district_names_and_drops_other_regions():
    seen: list[httpx.Request] = []
    rows = [
        {"signguCode": "F06-YD", "baseYmd": "20261120", "touDivCd": "1", "touNum": "100.5"},
        {"signguCode": "F06-YD", "baseYmd": "20261120", "touDivCd": "2", "touNum": 50},
        {"signguCode": "F06-HU", "baseYmd": "20261120", "touDivCd": "1", "touNum": 10},
        # 대응표에 없는 코드(부산 밖)는 버린다(거절로 세지 않는다).
        {"signguCode": "F99-XX", "baseYmd": "20261120", "touDivCd": "1", "touNum": 999},
    ]
    result = data06(httpx.Response(200, json=envelope(rows)), seen).fetch_day(date(2026, 11, 20))

    assert result.values == {(date(2026, 11, 20), "영도구"): [100.5, 50.0], (date(2026, 11, 20), "해운대구"): [10.0]}
    assert result.rejected == 0
    (request,) = seen
    assert request.url.path.endswith(DATA06_OPERATION)
    params = request.url.params
    assert (params["startYmd"], params["endYmd"], params["_type"], params["serviceKey"]) == (
        "20261120",
        "20261120",
        "json",
        FAKE_KEY,
    )


def test_data06_rejects_bad_items_only():
    rows = [
        {"signguCode": "F06-YD", "baseYmd": "20261120", "touNum": "abc"},
        {"signguCode": "F06-YD", "baseYmd": "20261121", "touNum": 5},  # 요청하지 않은 날짜
        {"signguCode": "F06-YD", "baseYmd": "20261120", "touNum": -1},
        "not-a-mapping",
        {"signguCode": "F06-YD", "baseYmd": "20261120", "touNum": 7},
    ]
    result = data06(httpx.Response(200, json=envelope(rows))).fetch_day(date(2026, 11, 20))  # type: ignore[arg-type]

    assert result.values == {(date(2026, 11, 20), "영도구"): [7.0]}
    assert result.rejected == 4


def test_data07_single_item_and_busan_absent():
    one = {"signguCd": "F07-YD", "baseYmd": "20261201", "tAtsNm": "가짜 관광지", "cnctrRate": "42.5"}
    result = data07(httpx.Response(200, json=envelope([one]))).fetch_region("영도구")
    assert result.values == {(date(2026, 12, 1), "영도구"): [42.5]}

    # 응답에 그 구·군 관광지가 없으면 빈 결과(오류 아님).
    empty = data07(httpx.Response(200, json=envelope(""))).fetch_region("영도구")
    assert empty.values == {} and empty.rejected == 0


def test_data07_sends_region_codes_and_rejects_other_region_items():
    seen: list[httpx.Request] = []
    rows = [
        {"signguCd": "F07-YD", "baseYmd": "20261201", "cnctrRate": 10},
        {"signguCd": "F07-OTHER", "baseYmd": "20261201", "cnctrRate": 90},
    ]
    result = data07(httpx.Response(200, json=envelope(rows)), seen).fetch_region("영도구")

    assert result.values == {(date(2026, 12, 1), "영도구"): [10.0]} and result.rejected == 1
    (request,) = seen
    assert request.url.path.endswith(DATA07_OPERATION)
    assert (request.url.params["areaCd"], request.url.params["signguCd"]) == ("FA", "F07-YD")


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(500, json={}), "DATA-07 요청 실패 (HTTP 500)"),
        (httpx.ReadTimeout("timed out"), "DATA-07 네트워크 요청 실패"),
        (
            httpx.Response(200, text="<OpenAPI_ServiceResponse>SERVICE_KEY_IS_NOT_REGISTERED_ERROR"),
            "DATA-07 JSON 처리 실패",
        ),
        (httpx.Response(200, json={"unexpected": 1}), "DATA-07 response 형식 오류"),
        (httpx.Response(200, json={"response": {"header": {"resultCode": "0000"}}}), "DATA-07 body 형식 오류"),
        (httpx.Response(200, json=envelope([], code="30")), "DATA-07 오류 응답 (resultCode 30)"),
        (httpx.Response(200, json={"response": {"body": {"items": [1]}}}), "DATA-07 items 형식 오류"),
        (
            httpx.Response(200, json=envelope([{"signguCd": "F07-YD"}], total=5)),
            "DATA-07 응답이 한 쪽을 넘습니다 (totalCount 5)",
        ),
    ],
)
def test_transport_and_format_errors_fail_whole_response(response: httpx.Response | Exception, message: str):
    with pytest.raises(VisitorTransportError) as raised:
        data07(response).fetch_region("영도구")

    assert str(raised.value) == message
    assert FAKE_KEY not in str(raised.value) and "serviceKey" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_region_code_table(tmp_path):
    path = tmp_path / "codes.csv"
    path.write_text(
        "# 가짜 코드(시험용)\nregion,data06_signgu_code,data07_area_code,data07_signgu_code\n"
        "영도구,F06-YD,FA,F07-YD\n해운대구,F06-HU,,\n기장군,,,\n",
        encoding="utf-8",
    )
    codes = load_region_codes(path)
    assert codes.data06 == {"F06-YD": "영도구", "F06-HU": "해운대구"}
    # DATA-07 은 두 코드가 다 있을 때만 쓴다.
    assert codes.data07 == {"영도구": ("FA", "F07-YD")}

    with pytest.raises(RegionCodeError):
        load_region_codes(tmp_path / "missing.csv")
    for bad in ("부산시,F1,,\n", "영도구,F1,,\n영도구,F2,,\n", "영도구,F1,,\n중구,F1,,\n"):
        path.write_text("region,data06_signgu_code,data07_area_code,data07_signgu_code\n" + bad, encoding="utf-8")
        with pytest.raises(RegionCodeError):
            load_region_codes(path)
    path.write_text("name,code\n영도구,F1\n", encoding="utf-8")
    with pytest.raises(RegionCodeError):
        load_region_codes(path)


def test_repository_region_table_lists_all_districts_without_unverified_codes():
    from app.adapters.public_data.settings import REGION_CODES

    text = REGION_CODES.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line and not line.startswith("#")][1:]
    assert [row.split(",")[0] for row in rows] == list(BUSAN_DISTRICTS)
    # 실제 코드를 확인하기 전까지 비워 둔다(지어낸 운영 값 금지).
    codes = load_region_codes(REGION_CODES)
    assert codes.data06 == {} and codes.data07 == {}


def test_settings_blank_key_is_missing_and_env_file_is_isolated(tmp_path):
    from app.adapters.public_data.settings import VisitorDataSettings

    # conftest 가 backend/.env 읽기를 끈다(개발자 키가 시험에 새지 않는다).
    assert VisitorDataSettings.model_config["env_file"] is None
    assert VisitorDataSettings().data06_key() is None and VisitorDataSettings().data07_key() is None
    settings = VisitorDataSettings(_env_file=None, data06_service_key="   ", data07_service_key="  k  ")
    assert (settings.data06_key(), settings.data07_key()) == (None, "k")

    env = tmp_path / ".env"
    env.write_text("DATA06_SERVICE_KEY=fake-from-file\nDATA06_BASELINE_DAYS=14\n", encoding="utf-8")
    from_file = VisitorDataSettings(_env_file=env)
    assert (from_file.data06_key(), from_file.data06_baseline_days) == ("fake-from-file", 14)
    assert "fake-from-file" not in repr(from_file)
