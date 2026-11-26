"""DATA-06·07 잡을 BatchCollector 로 돌린다(FR-008, FR-016, A3-7): 기록·한도·알림·중단·파일 유지.

SQLite(alembic)는 항상, PostgreSQL 은 TEST_DATABASE_URL 이 있을 때 돈다. API 는 httpx MockTransport 다.
응답·키·시군구 코드는 시험용 가짜(TEST FIXTURE)이며 실제 API 응답 복사가 아니다.
"""

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.adapters.public_data.settings import VisitorDataSettings
from app.batch.alerts import AdminAlert
from app.batch.cli import build_collector
from app.batch.collector import KST, BatchCollector
from app.batch.jobs.visitor_jobs import Data06Job, Data07Job
from app.batch.settings import BatchSettings
from app.db.models import DataSourceRow, IngestionRunRow
from app.db.session import Database
from app.modules.crowd.file_provider import FileCrowdProvider
from app.modules.crowd.signals import load_inputs
from tests.integration.test_db_persistence import DB_KINDS, open_database, upgrade

FAKE_KEY = "FAKE_DATA_KEY_5e2a"
WEBHOOK_URL = "https://hooks.example.test/secret-hook-path"
# 2026-11-26(목) 10:00 KST. DATA-06 기준 기간(lag 3, 7일) = 11-17(화)~11-23(월)
T0 = datetime(2026, 11, 26, 1, 0, tzinfo=UTC)
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "crowd"
CODES = (
    "# 가짜 코드(시험용, 실제 시군구 코드 아님)\n"
    "region,data06_signgu_code,data07_area_code,data07_signgu_code\n"
    "영도구,F06-YD,FA,F07-YD\n해운대구,F06-HU,FA,F07-HU\n기장군,,,\n"
)


def envelope(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "response": {
            "header": {"resultCode": "0000", "resultMsg": "OK"},
            "body": {"items": {"item": items} if items else "", "totalCount": len(items)},
        }
    }


@dataclass
class FakeAPI:
    """DATA-06 은 날짜별, DATA-07 은 signguCd 별로 응답한다. fail: 이 값(날짜 YYYYMMDD 또는 signguCd)이면 500."""

    fail: set[str] = field(default_factory=set)
    calls: list[str] = field(default_factory=list)
    # 있으면 각 응답 전에 부른다.
    on_call: Callable[[], None] | None = None
    # 명세와 다른 응답 흉내: DATA-06 값 필드 이름, 코드 뒤에 붙는 글자(자릿수 불일치), DATA-07 필드 이름
    data06_value_field: str = "touNum"
    data06_code_suffix: str = ""
    data07_value_field: str = "cnctrRate"
    # 있으면 DATA-07 영도구 예측을 이 날짜(YYYYMMDD)만 준다(값 40).
    data07_days: list[str] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.on_call is not None:
            self.on_call()
        params = request.url.params
        if "startYmd" in params:
            ymd = params["startYmd"]
            self.calls.append(ymd)
            if ymd in self.fail:
                return httpx.Response(500, json={})
            day = datetime.strptime(ymd, "%Y%m%d").date()
            # 영도구: 평일 100(23일은 200), 주말 21일 300·22일 100. 해운대구는 매일 50. 방문자 구분 1·2·3 합.
            yd = {21: 300, 22: 100, 23: 200}.get(day.day, 100)
            rows = []
            for code, parts in (("F06-YD", (yd / 2, yd / 4, yd / 4)), ("F06-HU", (50, 0, 0))):
                for index, value in enumerate(parts, start=1):
                    rows.append(
                        {
                            "signguCode": code + self.data06_code_suffix,
                            "baseYmd": ymd,
                            "touDivCd": str(index),
                            self.data06_value_field: value,
                        }
                    )
            rows.append({"signguCode": "F99-ZZ", "baseYmd": ymd, "touDivCd": "1", "touNum": 1})
            return httpx.Response(200, json=envelope(rows))
        code = params["signguCd"]
        self.calls.append(code)
        if code in self.fail:
            return httpx.Response(500, json={})
        if code == "F07-HU":
            # 부산 관광지 없음 → 빈 결과
            return httpx.Response(200, json=envelope([]))
        value = self.data07_value_field
        if self.data07_days is not None:
            return httpx.Response(
                200, json=envelope([{"signguCd": code, "baseYmd": ymd, value: 40} for ymd in self.data07_days])
            )
        # 영도구: 11-30(월) 20, 12-01(화) 40 → 평일 평균 30. 12-05(토) 50 하나 → 1.0
        rows = [
            {"signguCd": code, "baseYmd": "20261130", "tAtsNm": "가짜A", value: 10},
            {"signguCd": code, "baseYmd": "20261130", "tAtsNm": "가짜B", value: 30},
            {"signguCd": code, "baseYmd": "20261201", "tAtsNm": "가짜A", value: 40},
            {"signguCd": code, "baseYmd": "20261205", "tAtsNm": "가짜A", value: 50},
        ]
        return httpx.Response(200, json=envelope(rows))


@dataclass
class Clock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Harness:
    database: Database
    api: FakeAPI
    clock: Clock
    crowd_dir: Path
    webhook_bodies: list[dict[str, Any]]
    collector: BatchCollector

    @property
    def output(self) -> Path:
        return self.crowd_dir / "crowd_multipliers.csv"


@pytest.fixture(params=DB_KINDS)
def database(request: pytest.FixtureRequest) -> Iterator[Database]:
    database = open_database(request.param)
    upgrade(database)
    yield database
    database.dispose()


def make_harness(database: Database, tmp_path: Path, *, key: str | None = FAKE_KEY, codes: str = CODES) -> Harness:
    codes_path = tmp_path / "codes.csv"
    codes_path.write_text(codes, encoding="utf-8")
    settings = VisitorDataSettings(
        _env_file=None,
        data06_service_key=key,
        data07_service_key=key,
        data06_baseline_days=7,
        data06_lag_days=3,
        crowd_multiplier_retention_days=30,
        crowd_region_codes_path=codes_path,
    )
    api, clock, crowd_dir = FakeAPI(), Clock(T0), tmp_path / "crowd"
    bodies: list[dict[str, Any]] = []

    def webhook(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(api.handler))
    collector = BatchCollector(
        database,
        clock=clock,
        alert=AdminAlert(WEBHOOK_URL, client=httpx.Client(transport=httpx.MockTransport(webhook))),
        sources={
            "data06": Data06Job(settings, crowd_dir, clock=clock, client=client),
            "data07": Data07Job(settings, crowd_dir, clock=clock, client=client),
        },
    )
    for source_id in ("data06", "data07"):
        set_source(database, source_id, enabled=True)
    return Harness(database, api, clock, crowd_dir, bodies, collector)


def set_source(database: Database, source_id: str, **values: Any) -> None:
    with database.transaction() as session:
        source = session.get(DataSourceRow, source_id)
        assert source is not None
        for name, value in values.items():
            setattr(source, name, value)


def runs(database: Database, source_id: str) -> list[IngestionRunRow]:
    with database.transaction() as session:
        return list(
            session.scalars(
                select(IngestionRunRow)
                .where(IngestionRunRow.source_id == source_id)
                .order_by(IngestionRunRow.started_at)
            )
        )


def multipliers(h: Harness) -> dict[tuple[date, str], tuple[float, str]]:
    return {key: (round(item.value, 4), item.source) for key, item in load_inputs(h.crowd_dir).multipliers.items()}


def assert_no_secret(caplog: pytest.LogCaptureFixture, h: Harness) -> None:
    texts = [caplog.text, json.dumps(h.webhook_bodies, ensure_ascii=False)]
    texts += [run.error_message or "" for source in ("data06", "data07") for run in runs(h.database, source)]
    for value in texts:
        assert FAKE_KEY not in value
        assert "serviceKey" not in value
        assert "apis.data.go.kr" not in value
        assert "secret-hook-path" not in value


def test_seeded_sources_stay_disabled(database: Database, tmp_path: Path):
    with database.transaction() as session:
        rows = {row.id: (row.enabled, row.refresh_cycle) for row in session.scalars(select(DataSourceRow))}
    assert rows["data06"] == (False, "DAY") and rows["data07"] == (False, "DAY")

    collector = build_collector(database, BatchSettings(), visitor_settings=VisitorDataSettings(_env_file=None))
    assert {"tourapi", "data06", "data07"} <= set(collector.sources)
    run = collector.run("data06")
    assert run is not None and (run.status, run.call_count) == ("SKIPPED", 0)


def test_data06_success_writes_past_multipliers(database: Database, tmp_path: Path, caplog: pytest.LogCaptureFixture):
    h = make_harness(database, tmp_path)
    with caplog.at_level(logging.DEBUG):
        run = h.collector.run("data06")

    assert run is not None and run.status == "SUCCESS", run.error_message if run else None
    assert h.api.calls == [f"202611{day}" for day in range(17, 24)]
    # 영도구 7일 + 해운대구 7일. 부산 밖 코드는 버린다.
    assert (run.call_count, run.record_count, run.rejected_count) == (7, 14, 0)
    assert run.as_of == datetime(2026, 11, 23, tzinfo=KST)
    got = multipliers(h)
    # 평일 평균 120, 주말 평균 200(손계산)
    assert got[(date(2026, 11, 23), "영도구")] == (round(200 / 120, 4), "DATA-06")
    assert got[(date(2026, 11, 17), "영도구")] == (round(100 / 120, 4), "DATA-06")
    assert got[(date(2026, 11, 21), "영도구")] == (1.5, "DATA-06")
    assert got[(date(2026, 11, 22), "해운대구")] == (1.0, "DATA-06")
    # computed_at 은 쓰기 시각이다.
    assert {item.computed_at for item in load_inputs(h.crowd_dir).multipliers.values()} == {T0}
    assert_no_secret(caplog, h)


def test_data07_success_writes_future_rows_only_where_forecast_exists(
    database: Database, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    h = make_harness(database, tmp_path)
    with caplog.at_level(logging.DEBUG):
        run = h.collector.run("data07")

    assert run is not None and run.status == "SUCCESS"
    # 기장군은 DATA-07 코드가 없어 부르지 않는다. 해운대구는 빈 응답이라 행이 없다.
    assert h.api.calls == ["F07-YD", "F07-HU"]
    assert (run.call_count, run.record_count, run.as_of) == (2, 3, T0)
    assert multipliers(h) == {
        (date(2026, 11, 30), "영도구"): (round(20 / 30, 4), "DATA-07"),
        (date(2026, 12, 1), "영도구"): (round(40 / 30, 4), "DATA-07"),
        (date(2026, 12, 5), "영도구"): (1.0, "DATA-07"),
    }
    assert_no_secret(caplog, h)


def test_m_applies_only_on_forecast_dates(database: Database, tmp_path: Path):
    """파일 제공자: 예측 행이 있는 날은 M 이 신호로 들어가고, 없는 미래 날짜는 M 미적용·미계상이다."""
    h = make_harness(database, tmp_path)
    h.collector.run("data07")
    for name in ("living_population.csv", "metro_hourly.csv", "place_signal_links.csv"):
        (h.crowd_dir / name).write_bytes((FIXTURES / name).read_bytes())
    links = load_inputs(h.crowd_dir).links
    place_id = next(iter(links))
    provider = FileCrowdProvider.from_dir(h.crowd_dir, lambda _: "영도구")

    with_m = provider.find(place_id, date(2026, 12, 1))
    without_m = provider.find(place_id, date(2026, 12, 2))
    assert with_m is not None and without_m is not None
    assert "DATA-07" in [signal.source for signal in with_m.signals]
    assert "DATA-07" not in [signal.source for signal in without_m.signals]
    assert with_m.as_of == T0


def test_failure_keeps_previous_file_and_alerts(database: Database, tmp_path: Path, caplog: pytest.LogCaptureFixture):
    h = make_harness(database, tmp_path)
    assert h.collector.run("data06").status == "SUCCESS"  # type: ignore[union-attr]
    assert h.collector.run("data07").status == "SUCCESS"  # type: ignore[union-attr]
    before = h.output.read_bytes()

    h.clock.now = T0 + timedelta(days=1)
    h.api.fail = {"20261121", "F07-HU"}
    h.api.calls.clear()
    with caplog.at_level(logging.INFO):
        failed06 = h.collector.run("data06")
        failed07 = h.collector.run("data07")

    assert failed06 is not None and (failed06.status, failed06.error_message) == (
        "FAILED",
        "DATA-06 요청 실패 (HTTP 500)",
    )
    # 실패한 호출까지 센다(11-18 부터 하루 밀린 기간의 넷째 날이 21일).
    assert failed06.call_count == 4 and failed06.record_count is None
    assert failed07 is not None and (failed07.status, failed07.call_count) == ("FAILED", 2)
    assert h.output.read_bytes() == before
    assert [body["source"] for body in h.webhook_bodies] == ["data06", "data07"]
    assert {body["status"] for body in h.webhook_bodies} == {"FAILED"}
    assert_no_secret(caplog, h)


@pytest.mark.parametrize(
    ("key", "codes", "message"),
    [
        (None, CODES, "DATA06_SERVICE_KEY가 설정되지 않았습니다."),
        ("   ", CODES, "DATA06_SERVICE_KEY가 설정되지 않았습니다."),
        (FAKE_KEY, "region,data06_signgu_code,data07_area_code,data07_signgu_code\n영도구,,,\n", None),
    ],
)
def test_missing_key_or_codes_fails_without_calls(
    database: Database, tmp_path: Path, key: str | None, codes: str, message: str | None
):
    h = make_harness(database, tmp_path, key=key, codes=codes)
    run = h.collector.run("data06")

    assert run is not None and run.status == "FAILED" and run.call_count == 0
    assert run.error_message == (message or "지역 코드 대응표에 DATA-06 코드가 없습니다.")
    assert h.api.calls == [] and not h.output.exists()
    assert len(h.webhook_bodies) == 1


def test_daily_call_limit_skips_without_calls(database: Database, tmp_path: Path):
    h = make_harness(database, tmp_path)
    set_source(database, "data06", daily_call_limit=10)
    assert h.collector.run("data06").status == "SUCCESS"  # type: ignore[union-attr]
    h.api.calls.clear()
    run = h.collector.run("data06")

    # 7 + 7 > 10
    assert run is not None and run.status == "SKIPPED" and run.error_message is not None
    assert "daily call limit" in run.error_message and h.api.calls == []


def test_stop_interrupts_between_calls_without_writing(database: Database, tmp_path: Path):
    h = make_harness(database, tmp_path)
    h.api.on_call = h.collector.stop.set
    run = h.collector.run("data06")

    assert run is not None and (run.status, run.error_message, run.call_count) == ("FAILED", "interrupted", 1)
    assert not h.output.exists()


def test_run_due_runs_both_daily_sources(database: Database, tmp_path: Path):
    h = make_harness(database, tmp_path)
    assert {run.source_id: run.status for run in h.collector.run_due()} == {"data06": "SUCCESS", "data07": "SUCCESS"}
    sources = {item.source for item in load_inputs(h.crowd_dir).multipliers.values()}
    assert sources == {"DATA-06", "DATA-07"}
    # 같은 KST 날짜에는 다시 돌지 않는다(DAY 주기).
    h.clock.now = T0 + timedelta(hours=5)
    assert h.collector.run_due() == []


@pytest.mark.parametrize(
    ("source_id", "mismatch", "message"),
    [
        # 값 필드 이름이 명세와 다름 → 모든 항목 거절
        ("data06", {"data06_value_field": "touCnt"}, "DATA-06 no usable rows (rejected=6, unmapped=1)"),
        # 대응표는 짧은 코드인데 응답은 10자리(가짜) → 부산 구·군이 하나도 맞지 않음
        ("data06", {"data06_code_suffix": "00000"}, "DATA-06 no usable rows (rejected=0, unmapped=7)"),
        ("data07", {"data07_value_field": "cnctrRt"}, "DATA-07 no usable rows (rejected=4, unmapped=0)"),
    ],
)
def test_spec_mismatch_fails_and_alerts_instead_of_empty_success(
    database: Database, tmp_path: Path, source_id: str, mismatch: dict[str, str], message: str
):
    h = make_harness(database, tmp_path)
    h.collector.run("data06")
    before = h.output.read_bytes()
    h.clock.now = T0 + timedelta(days=1)
    for name, value in mismatch.items():
        setattr(h.api, name, value)
    run = h.collector.run(source_id)

    assert run is not None and (run.status, run.error_message) == ("FAILED", message)
    # 첫 응답에서 멈춘다. 기존 파일·기준 시각은 그대로다.
    assert run.call_count == 1 and run.as_of is None and run.record_count is None
    assert h.output.read_bytes() == before
    assert [(body["source"], body["status"]) for body in h.webhook_bodies] == [(source_id, "FAILED")]


def test_data06_all_empty_responses_fail_without_fresh_as_of(database: Database, tmp_path: Path):
    h = make_harness(database, tmp_path)
    job = h.collector.sources["data06"]
    assert isinstance(job, Data06Job)
    job._client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=envelope([]))))
    run = h.collector.run("data06")

    assert run is not None and (run.status, run.error_message, run.as_of) == (
        "FAILED",
        "DATA-06 no usable rows (rejected=0, unmapped=0)",
        None,
    )


def test_data06_as_of_is_latest_used_date(database: Database, tmp_path: Path):
    h = make_harness(database, tmp_path)
    # 마지막 날(23일) 자료가 아직 없고(빈 응답) 22일 해운대구 항목 하나가 거절되면,
    # as_of 는 실제로 쓴 가장 늦은 날(22일)이고 22일 해운대구는 빠진다.
    handler = h.api.handler

    def last_day_missing(request: httpx.Request) -> httpx.Response:
        ymd = request.url.params.get("startYmd")
        if ymd == "20261123":
            return httpx.Response(200, json=envelope([]))
        response = handler(request)
        if ymd == "20261122":
            payload = json.loads(response.content)
            payload["response"]["body"]["items"]["item"][3]["touNum"] = "x"
            return httpx.Response(200, json=payload)
        return response

    job = h.collector.sources["data06"]
    assert isinstance(job, Data06Job)
    job._client = httpx.Client(transport=httpx.MockTransport(last_day_missing))
    run = h.collector.run("data06")

    assert run is not None and run.status == "SUCCESS", run.error_message if run else None
    assert run.as_of == datetime(2026, 11, 22, tzinfo=KST) and run.rejected_count == 1
    got = multipliers(h)
    assert (date(2026, 11, 23), "영도구") not in got and (date(2026, 11, 22), "해운대구") not in got
    # 21일만 남은 해운대구 주말 평균 = 21일 값 → 1.0
    assert got[(date(2026, 11, 21), "해운대구")] == (1.0, "DATA-06")


def test_data07_new_forecast_replaces_stale_future_rows(database: Database, tmp_path: Path):
    h = make_harness(database, tmp_path)
    assert h.collector.run("data07").status == "SUCCESS"  # type: ignore[union-attr]
    assert set(multipliers(h)) == {
        (date(2026, 11, 30), "영도구"),
        (date(2026, 12, 1), "영도구"),
        (date(2026, 12, 5), "영도구"),
    }

    # 다음 날 예측에는 12-01 만 있다 → 오늘 이후의 옛 DATA-07 행(11-30·12-05)은 지운다.
    h.clock.now = T0 + timedelta(days=1)
    h.api.data07_days = ["20261201"]
    run = h.collector.run("data07")

    assert run is not None and (run.status, run.record_count) == ("SUCCESS", 1)
    assert multipliers(h) == {(date(2026, 12, 1), "영도구"): (1.0, "DATA-07")}

    # 대응표에서 구·군이 빠지거나 응답이 모두 비어도 옛 미래 예측을 남기지 않는다.
    h.clock.now = T0 + timedelta(days=2)
    h.api.data07_days = []
    run = h.collector.run("data07")
    assert run is not None and (run.status, run.record_count) == ("SUCCESS", 0)
    assert multipliers(h) == {}


def test_retention_prunes_old_rows(database: Database, tmp_path: Path):
    h = make_harness(database, tmp_path)
    h.collector.run("data06")
    old = set(multipliers(h))
    # 보존 기간(시험 설정 30일)보다 오래된 DATA-06 행은 다음 쓰기에서 지운다.
    h.clock.now = T0 + timedelta(days=40)
    h.collector.run("data06")

    kept = set(multipliers(h))
    assert not (old & kept)
    assert min(day for day, _ in kept) >= (h.clock.now.astimezone(KST).date() - timedelta(days=30))
