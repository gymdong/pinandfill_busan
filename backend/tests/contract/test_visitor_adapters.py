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


def visitors(code: str, ymd: str, values: tuple[float, ...] = (60, 30, 10), **extra: Any) -> list[dict[str, Any]]:
    """방문자 구분 1·2·3(가짜 값) 한 벌."""
    return [
        {"signguCode": code, "baseYmd": ymd, "touDivCd": str(index), "touNum": value, **extra}
        for index, value in enumerate(values, start=1)
    ]


DAY = date(2026, 11, 20)


def test_data06_maps_codes_to_district_names_and_drops_other_regions():
    seen: list[httpx.Request] = []
    rows = [
        *visitors("F06-YD", "20261120", ("100.5", 50, 0)),
        *visitors("F06-HU", "20261120", (10, 0, 0)),
        # 대응표에 없는 코드(부산 밖)는 버린다(거절로 세지 않는다).
        {"signguCode": "F99-XX", "baseYmd": "20261120", "touDivCd": "1", "touNum": 999},
    ]
    result = data06(httpx.Response(200, json=envelope(rows)), seen).fetch_day(DAY)

    assert result.usable() == {(DAY, "영도구"): [100.5, 50.0, 0.0], (DAY, "해운대구"): [10.0, 0.0, 0.0]}
    assert (result.received, result.rejected, result.unmapped) == (7, 0, 1)
    (request,) = seen
    assert request.url.path.endswith(DATA06_OPERATION)
    params = request.url.params
    assert (params["startYmd"], params["endYmd"], params["_type"], params["serviceKey"]) == (
        "20261120",
        "20261120",
        "json",
        FAKE_KEY,
    )


def test_data06_rejected_item_excludes_its_region_day():
    yd = visitors("F06-YD", "20261120")
    yd[1]["touNum"] = "abc"
    rows = [*yd, *visitors("F06-HU", "20261120")]
    result = data06(httpx.Response(200, json=envelope(rows))).fetch_day(DAY)

    # 영도구 합이 줄지 않게 그날 영도구를 통째로 뺀다. 해운대구는 쓴다.
    assert result.usable() == {(DAY, "해운대구"): [60.0, 30.0, 10.0]}
    assert result.rejected == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"baseYmd": "20261121"},  # 요청하지 않은 날짜
        {"touNum": -1},
        {"touDivCd": "9"},  # 모르는 방문자 구분
    ],
)
def test_data06_invalid_item_variants_are_rejected(bad: dict[str, Any]):
    yd = visitors("F06-YD", "20261120")
    yd[0].update(bad)
    result = data06(httpx.Response(200, json=envelope([*yd, *visitors("F06-HU", "20261120")]))).fetch_day(DAY)
    assert set(result.usable()) == {(DAY, "해운대구")} and result.rejected == 1


def test_data06_missing_or_duplicate_visitor_type_excludes_region_day():
    missing = visitors("F06-YD", "20261120")[:2]
    duplicate = visitors("F06-HU", "20261120") + visitors("F06-HU", "20261120")[:1]
    ok = data06(httpx.Response(200, json=envelope([*visitors("F06-YD", "20261120")]))).fetch_day(DAY)
    assert set(ok.usable()) == {(DAY, "영도구")}

    with pytest.raises(VisitorTransportError, match=r"no usable rows \(rejected=0, unmapped=0\)"):
        data06(httpx.Response(200, json=envelope([*missing, *duplicate]))).fetch_day(DAY)


def test_data06_item_without_code_excludes_whole_day():
    rows = [*visitors("F06-YD", "20261120"), *visitors("F06-HU", "20261120"), {"baseYmd": "20261120", "touNum": 1}]
    with pytest.raises(VisitorTransportError, match=r"DATA-06 no usable rows \(rejected=1, unmapped=0\)"):
        data06(httpx.Response(200, json=envelope(rows))).fetch_day(DAY)


def test_data06_typo_field_fails_instead_of_empty_success():
    rows = [{"signguCode": "F06-YD", "baseYmd": "20261120", "touDivCd": "1", "touCnt": 10}]
    with pytest.raises(VisitorTransportError) as raised:
        data06(httpx.Response(200, json=envelope(rows))).fetch_day(DAY)
    assert str(raised.value) == "DATA-06 no usable rows (rejected=1, unmapped=0)"


def test_data06_code_format_mismatch_fails():
    # 대응표는 5자리인데 응답이 10자리(가짜)면 부산 구·군이 하나도 맞지 않는다.
    rows = [*visitors("F06-YD00000", "20261120"), *visitors("F06-HU00000", "20261120")]
    with pytest.raises(VisitorTransportError) as raised:
        data06(httpx.Response(200, json=envelope(rows))).fetch_day(DAY)
    assert str(raised.value) == "DATA-06 no usable rows (rejected=0, unmapped=6)"


def test_data06_empty_response_is_not_an_error():
    result = data06(httpx.Response(200, json=envelope(""))).fetch_day(DAY)
    assert result.usable() == {} and result.received == 0


def test_data07_single_item_and_busan_absent():
    one = {"signguCd": "F07-YD", "baseYmd": "20261201", "tAtsNm": "가짜 관광지", "cnctrRate": "42.5"}
    result = data07(httpx.Response(200, json=envelope([one]))).fetch_region("영도구")
    assert result.usable() == {(date(2026, 12, 1), "영도구"): [42.5]}

    # 응답에 그 구·군 관광지가 없으면 빈 결과(오류 아님).
    empty = data07(httpx.Response(200, json=envelope(""))).fetch_region("영도구")
    assert empty.usable() == {} and empty.rejected == 0


def test_data07_sends_region_codes_and_drops_other_region_items():
    seen: list[httpx.Request] = []
    rows = [
        {"signguCd": "F07-YD", "baseYmd": "20261201", "cnctrRate": 10},
        {"signguCd": "F07-OTHER", "baseYmd": "20261201", "cnctrRate": 90},
    ]
    result = data07(httpx.Response(200, json=envelope(rows)), seen).fetch_region("영도구")

    assert result.usable() == {(date(2026, 12, 1), "영도구"): [10.0]}
    assert (result.rejected, result.unmapped) == (0, 1)
    (request,) = seen
    assert request.url.path.endswith(DATA07_OPERATION)
    assert (request.url.params["areaCd"], request.url.params["signguCd"]) == ("FA", "F07-YD")


def test_data07_rejected_item_excludes_that_date():
    rows = [
        {"signguCd": "F07-YD", "baseYmd": "20261201", "cnctrRate": 10},
        {"signguCd": "F07-YD", "baseYmd": "20261201", "cnctrRate": "x"},
        {"signguCd": "F07-YD", "baseYmd": "20261202", "cnctrRate": 20},
    ]
    result = data07(httpx.Response(200, json=envelope(rows))).fetch_region("영도구")
    assert result.usable() == {(date(2026, 12, 2), "영도구"): [20.0]} and result.rejected == 1

    # 날짜를 모르는 거절 항목이면 그 구·군 전체를 빼므로 쓸 행이 없다.
    rows[1]["baseYmd"] = ""
    with pytest.raises(VisitorTransportError, match=r"DATA-07 no usable rows \(rejected=1, unmapped=0\)"):
        data07(httpx.Response(200, json=envelope(rows))).fetch_region("영도구")


def test_data07_typo_field_fails():
    rows = [{"signguCd": "F07-YD", "baseYmd": "20261201", "cnctrRt": 10}]
    with pytest.raises(VisitorTransportError, match=r"DATA-07 no usable rows \(rejected=1, unmapped=0\)"):
        data07(httpx.Response(200, json=envelope(rows))).fetch_region("영도구")


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
        (httpx.Response(200, json={"response": {"body": {"items": ""}}}), "DATA-07 header 형식 오류"),
        (httpx.Response(200, json={"response": {"header": {}, "body": {}}}), "DATA-07 header 형식 오류"),
        (httpx.Response(200, json={"response": {"header": {"resultCode": "0000"}}}), "DATA-07 body 형식 오류"),
        (httpx.Response(200, json=envelope([], code="30")), "DATA-07 오류 응답 (resultCode 30)"),
        (
            httpx.Response(200, json={"response": {"header": {"resultCode": "0000"}, "body": {"items": [1]}}}),
            "DATA-07 items 형식 오류",
        ),
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

    # 보존 기간이 기준 기간 + 지연보다 짧으면 방금 계산한 행을 지우므로 설정 오류다.
    with pytest.raises(ValueError):
        VisitorDataSettings(
            _env_file=None, data06_baseline_days=28, data06_lag_days=3, crowd_multiplier_retention_days=30
        )
