"""혼잡 원본 → 정규화 CSV 변환(app.modules.crowd.importers). 값은 형식만 맞춘 시험용이다."""

from pathlib import Path

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.modules.crowd.importers import (
    DATA04_URL,
    Data04Settings,
    fetch_living,
    main,
    normalize_living,
    normalize_metro,
)
from app.modules.crowd.signals import load_inputs

HOURS = ["01시-02시", "02시-03시", *[f"{h:02d}시-{h + 1:02d}시" for h in range(3, 24)], "24시-01시"]
HEADER = "역번호,역명,년월일,요일,구분,합계," + ",".join(HOURS)


def _row(code: str, day: str, kind: str, value: int) -> str:
    # 01시-02시 칸만 value, 나머지 0. 24시-01시(→ 0시) 칸은 1
    cells = [str(value)] + ["0"] * 22 + ["1"]
    return f"{code},역{code},{day},X,{kind},{value + 1}," + ",".join(cells)


def test_metro_averages_per_day_type_and_maps_hours() -> None:
    text = "\n".join(
        [
            HEADER,
            _row("209", "2026-10-03", "승차", 10),  # 토
            _row("209", "2026-10-03", "하차", 4),
            _row("209", "2026-10-04", "승차", 30),  # 일
            _row("209", "2026-10-04", "하차", 6),
            _row("209", "2026-10-05", "승차", 7),  # 월
            _row("209", "2026-10-05", "하차", 1),
        ]
    )
    rows, report = normalize_metro(text)
    by = {(r["day_type"], r["hour"]): r for r in rows}
    assert by[("WEEKEND", 1)]["boardings"] == 20.0
    assert by[("WEEKEND", 1)]["alightings"] == 5.0
    assert by[("WEEKDAY", 1)]["boardings"] == 7.0
    assert by[("WEEKDAY", 0)]["boardings"] == 1.0
    assert {r["hour"] for r in rows} == set(range(24))
    assert report.skipped == 0


def test_metro_keeps_latest_months_and_skips_broken_rows() -> None:
    broken = _row("209", "2026-10-06", "승차", 1).replace(",0,0,", ",x,0,", 1)
    text = "\n".join([HEADER, _row("209", "2026-09-07", "승차", 1), _row("209", "2026-10-05", "승차", 1), broken])
    rows, report = normalize_metro(text, months=1)
    assert {r["ref_month"] for r in rows} == {"2026-10"}
    assert report.skipped == 1
    assert {r["ref_month"] for r in normalize_metro(text, months=None)[0]} == {"2026-09", "2026-10"}


def test_metro_rejects_unknown_header() -> None:
    with pytest.raises(ValueError):
        normalize_metro("역번호,역명,년월일\n1,a,2026-10-01")


def test_living_sums_population_types_for_both_day_types() -> None:
    items = [
        {"stdYm": "202609", "hcode": "2650077000", "times": "14시", "hpopAvg": "10", "wpopAvg": "2", "vpopAvg": "3"},
        {"stdYm": "202609", "hcode": "2650077000", "times": "14시", "hpopAvg": "99", "wpopAvg": "0", "vpopAvg": "0"},
        {"stdYm": "202609", "hcode": "2650077000", "times": "24시", "hpopAvg": "1", "wpopAvg": "1", "vpopAvg": "1"},
        {"stdYm": "202609", "hcode": "2650077000", "times": "15시", "hpopAvg": "", "wpopAvg": "1", "vpopAvg": "1"},
    ]
    rows, report = normalize_living(items)
    assert rows == [
        {"ref_month": "2026-09", "adm_dong_code": "2650077000", "day_type": d, "hour": 14, "population": 15}
        for d in ("WEEKDAY", "WEEKEND")
    ]
    assert report.skipped == 3


def _page(items: list[dict[str, str]], total: int) -> dict[str, object]:
    return {"response": {"header": {"resultCode": "00"}, "body": {"totalCount": str(total), "items": {"item": items}}}}


ITEM = {"stdYm": "202609", "hcode": "1", "times": "00시", "hpopAvg": "1", "wpopAvg": "1", "vpopAvg": "1"}


@respx.mock
def test_fetch_living_pages_until_total() -> None:
    pages = [_page([ITEM] * 1000, 1001), _page([ITEM], 1001)]
    route = respx.get(DATA04_URL).mock(side_effect=[httpx.Response(200, json=page) for page in pages])
    items = list(fetch_living("202609", Data04Settings(_env_file=None, data04_service_key=SecretStr("k"))))
    assert len(items) == 1001
    assert route.call_count == 2


@respx.mock
def test_fetch_living_fails_on_bad_envelope_without_leaking_key() -> None:
    respx.get(DATA04_URL).mock(return_value=httpx.Response(200, text="<result><resultCode>03</resultCode></result>"))
    with pytest.raises(RuntimeError) as error:
        list(fetch_living("202610", Data04Settings(_env_file=None, data04_service_key=SecretStr("secret-key"))))
    assert "secret-key" not in str(error.value)


def test_fetch_living_requires_key() -> None:
    with pytest.raises(RuntimeError):
        list(fetch_living("202609", Data04Settings(_env_file=None, data04_service_key=None)))


def test_cli_metro_writes_file_the_provider_reads(tmp_path: Path) -> None:
    source = tmp_path / "raw.csv"
    source.write_bytes((HEADER + "\n" + _row("209", "2026-10-03", "승차", 10) + "\n").encode("cp949"))
    assert main(["--out-dir", str(tmp_path), "metro", str(source)]) == 0
    inputs = load_inputs(tmp_path)
    assert inputs.profiles[("DATA-05", "209")]["2026-10"][("WEEKEND", 1)] == 10.0


def test_living_keeps_numeric_zero_and_rounds_decimals() -> None:
    item = {"stdYm": "202609", "hcode": "1", "times": "03시", "hpopAvg": 10, "wpopAvg": 0, "vpopAvg": "2.6"}
    rows, report = normalize_living([item])
    assert report.skipped == 0 and rows[0]["population"] == 13


@respx.mock
def test_fetch_living_rejects_error_result_code() -> None:
    page = {"response": {"header": {"resultCode": "30"}, "body": {"totalCount": "1", "items": {"item": [ITEM]}}}}
    respx.get(DATA04_URL).mock(return_value=httpx.Response(200, json=page))
    with pytest.raises(RuntimeError):
        list(fetch_living("202609", Data04Settings(_env_file=None, data04_service_key=SecretStr("k"))))


def test_cli_rejects_negative_months(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--out-dir", str(tmp_path), "metro", str(tmp_path / "x.csv"), "--months", "-1"])
