"""DATA-06·07 날짜 배수 수집 잡(FR-008, FR-016). `BatchCollector` 의 `SourceJob` 구현.

- `Data06Job`(data06): 최근 기준 기간(DATA06_BASELINE_DAYS 일, 오늘 KST − DATA06_LAG_DAYS 까지)을 하루 1회씩 받아
  과거 날짜 배수를 만든다. 호출 수 = 기준 기간 일수. 쓸 수 있는 행이 하나도 없으면 FAILED 다(SUCCESS 로 넘기지 않는다).
  as_of 는 실제로 쓴 가장 늦은 자료일(KST 0시)이다.
- `Data07Job`(data07): 대응표에 DATA-07 코드가 있는 구·군마다 1회 받아 향후 30일 날짜 배수를 만든다.
  호출 수 = 그 구·군 수. 미래 날짜의 M 은 이 잡만 만든다. 오늘(KST) 이후의 DATA-07 행은 매번 새 예측으로 통째로 바꾼다.
  모든 구·군 응답이 비면 FAILED('DATA-07 all regions empty') + 알림이고 쓰지 않는다(코드가 틀렸을 수 있어
  미래 예측을 통째로 지우지 않는다). 일부만 비면 그 구·군은 행 없이 SUCCESS 이고 빈 구·군 수를 로그에 남긴다.
  항목이 왔는데 쓸 수 있는 행이 없으면 FAILED 다.

결과는 CROWD_DATA_DIR(기본 data/crowd)/crowd_multipliers.csv 에 합쳐 쓴다(`multipliers.write_multipliers`).
두 소스 모두 CROWD_MULTIPLIER_RETENTION_DAYS 보다 오래된 자기 행은 지운다.
쓰기는 수집기가 성공으로 판정한 뒤에만 불리므로, 한 번이라도 전송 오류가 나면 기존 파일이 그대로 남는다.
파일 교체는 DB 커밋(SUCCESS 기록)보다 먼저 일어난다. 커밋이 실패하면 파일이 실행 기록보다 새것일 수 있다(허용).
앱은 시작 때 파일을 읽으므로 새 배수는 앱을 다시 시작해야 보인다.
"""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from app.adapters.public_data.regions import RegionCodeError, RegionCodes, load_region_codes
from app.adapters.public_data.settings import VisitorDataSettings
from app.adapters.public_data.visitors import (
    ConcentrationForecastAdapter,
    Fetched,
    VisitorCountAdapter,
    VisitorTransportError,
)
from app.core.logging import quiet_http_client_logs
from app.db.session import Database
from app.modules.crowd.multipliers import day_type_ratios, write_multipliers
from app.modules.crowd.signals import KST

from ..collector import INTERRUPTED, JobOutcome

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]


def _now() -> datetime:
    return datetime.now(UTC)


class _VisitorJob:
    source = ""
    key_name = ""

    def __init__(
        self,
        settings: VisitorDataSettings,
        output_dir: Path,
        *,
        clock: Clock = _now,
        client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._output_dir = output_dir
        self._clock = clock
        self._client = client
        # 요청 URL 에 serviceKey 가 들어가므로 httpx 가 URL 을 로그에 남기지 않게 한다.
        quiet_http_client_logs()

    def _api_key(self) -> str | None:
        raise NotImplementedError

    def _regions(self) -> RegionCodes:
        return load_region_codes(self._settings.crowd_region_codes_path)

    def _http(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=self._settings.public_data_timeout_s)

    def _today(self) -> date:
        return self._clock().astimezone(KST).date()

    def _write(self, ratios: dict[tuple[date, str], float], *, replace_since: date | None) -> Callable[[datetime], int]:
        prune_before = self._today() - timedelta(days=self._settings.crowd_multiplier_retention_days)

        def write(at: datetime) -> int:
            return write_multipliers(
                self._output_dir, self.source, ratios, at, replace_since=replace_since, prune_before=prune_before
            )

        return write

    def _precheck(self) -> tuple[str, RegionCodes] | JobOutcome:
        key = self._api_key()
        if not key:
            # 키가 없으면 호출하지 않는다(BatchSettings 와 같이 설정으로만 받는다).
            return JobOutcome(call_count=0, error=f"{self.key_name}가 설정되지 않았습니다.")
        try:
            return key, self._regions()
        except RegionCodeError as exc:
            return JobOutcome(call_count=0, error=str(exc))


class Data06Job(_VisitorJob):
    source = "DATA-06"
    key_name = "DATA06_SERVICE_KEY"

    def _api_key(self) -> str | None:
        return self._settings.data06_key()

    def days(self) -> list[date]:
        end = self._today() - timedelta(days=self._settings.data06_lag_days)
        count = self._settings.data06_baseline_days
        return [end - timedelta(days=offset) for offset in range(count - 1, -1, -1)]

    def planned_calls(self, database: Database) -> int:
        return self._settings.data06_baseline_days

    def collect(self, database: Database, should_stop: Callable[[], bool]) -> JobOutcome:
        checked = self._precheck()
        if isinstance(checked, JobOutcome):
            return checked
        key, regions = checked
        if not regions.data06:
            return JobOutcome(call_count=0, error="지역 코드 대응표에 DATA-06 코드가 없습니다.")
        fetched, calls = Fetched(), 0
        client = self._http()
        try:
            adapter = VisitorCountAdapter(key, regions, client, page_size=self._settings.public_data_page_size)
            for day in self.days():
                if should_stop():
                    return JobOutcome(call_count=calls, rejected_count=fetched.rejected, error=INTERRUPTED)
                calls += 1
                fetched.add(adapter.fetch_day(day))
        except VisitorTransportError as exc:
            return JobOutcome(call_count=calls, rejected_count=fetched.rejected, error=str(exc))
        finally:
            if self._client is None:
                client.close()
        ratios = day_type_ratios(fetched.usable(), combine="sum")
        if not ratios:
            # 과거 자료가 하나도 없으면 실행 시각을 기준 시각으로 남기지 않는다(성공처럼 보이지 않게).
            return JobOutcome(
                call_count=calls, rejected_count=fetched.rejected, error=fetched.no_usable_rows("DATA-06")
            )
        latest = max(day for day, _ in ratios)
        return JobOutcome(
            call_count=calls,
            rejected_count=fetched.rejected,
            as_of=datetime(latest.year, latest.month, latest.day, tzinfo=KST),
            write=self._write(ratios, replace_since=None),
        )


class Data07Job(_VisitorJob):
    source = "DATA-07"
    key_name = "DATA07_SERVICE_KEY"

    def _api_key(self) -> str | None:
        return self._settings.data07_key()

    def planned_calls(self, database: Database) -> int:
        try:
            return len(self._regions().data07)
        except RegionCodeError:
            return 0

    def collect(self, database: Database, should_stop: Callable[[], bool]) -> JobOutcome:
        checked = self._precheck()
        if isinstance(checked, JobOutcome):
            return checked
        key, regions = checked
        if not regions.data07:
            return JobOutcome(call_count=0, error="지역 코드 대응표에 DATA-07 코드가 없습니다.")
        fetched, calls, empty_regions = Fetched(), 0, 0
        client = self._http()
        try:
            adapter = ConcentrationForecastAdapter(key, regions, client, page_size=self._settings.public_data_page_size)
            for region in regions.data07:
                if should_stop():
                    return JobOutcome(call_count=calls, rejected_count=fetched.rejected, error=INTERRUPTED)
                calls += 1
                result = adapter.fetch_region(region)
                empty_regions += result.received == 0
                fetched.add(result)
        except VisitorTransportError as exc:
            return JobOutcome(call_count=calls, rejected_count=fetched.rejected, error=str(exc))
        finally:
            if self._client is None:
                client.close()
        if empty_regions == calls:
            # 대응표 코드(areaCd·signguCd)가 틀려도 이렇게 보인다. 옛 예측을 지우지 않고 실패로 알린다.
            return JobOutcome(call_count=calls, error="DATA-07 all regions empty")
        if empty_regions:
            logger.warning("data07_empty_regions empty=%d regions=%d", empty_regions, calls)
        ratios = day_type_ratios(fetched.usable(), combine="mean")
        if not ratios:
            return JobOutcome(
                call_count=calls, rejected_count=fetched.rejected, error=fetched.no_usable_rows("DATA-07")
            )
        # 예측은 실행 시각 기준이다(as_of=None → 수집기가 실행 시각을 쓴다).
        return JobOutcome(
            call_count=calls,
            rejected_count=fetched.rejected,
            write=self._write(ratios, replace_since=self._today()),
        )
