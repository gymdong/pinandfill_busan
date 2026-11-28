"""FR-013 날씨: 블록 시각의 기상청 예보(API-016)와 비 예보 판정(플랜 B 트리거).

- 단기예보 범위(약 3일) 안이면 시간 단위(SHORT), 중기예보 범위(4~10일)면 일 단위(MID), 밖이면 None('예보 없음').
- 같은 격자·같은 발표의 예보는 `kma_cache_s` 동안 다시 받지 않는다. 조회가 실패하면 None 이다(ERR-012, 일정은 그대로).
  SDD 는 배치 수집(weather_forecasts)을 정하지만, 지금은 요청 때 조회하고 메모리에 잠깐 둔다(잠정).
- 일 단위 예보로는 자동 조정하지 않는다(SRS FR-013). 비 예보 판정(`rain`)은 SHORT 일 때만 참이 될 수 있다.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from threading import Lock
from typing import Literal, Protocol

from app.modules.weather.grid import to_grid
from app.modules.weather.kma import KmaError, MidForecast, ShortForecast, mid_base, short_base
from app.modules.weather.settings import WeatherSettings

logger = logging.getLogger(__name__)

RAIN_TYPES = frozenset({"비", "비/눈", "눈", "소나기"})


class KmaSource(Protocol):
    def short(self, nx: int, ny: int, base: datetime) -> ShortForecast: ...

    def mid(self, base: datetime) -> MidForecast: ...


@dataclass(frozen=True, slots=True)
class Forecast:
    scope: Literal["SHORT", "MID"]
    issued_at: datetime
    pop: int | None
    pty: str | None
    sky: str | None
    temp: float | None
    wind: float | None
    temp_min: float | None = None
    temp_max: float | None = None
    # 비 예보(강수형태 비·눈이거나 강수확률이 기준 이상). 일 단위 예보는 자동 조정에 쓰지 않으므로 항상 False.
    rain: bool = False


def _now() -> datetime:
    return datetime.now(UTC)


class WeatherService:
    def __init__(self, source: KmaSource, settings: WeatherSettings, *, clock: Callable[[], datetime] = _now) -> None:
        self.source = source
        self.settings = settings
        self.clock = clock
        self._lock = Lock()
        self._short: dict[tuple[int, int, datetime], tuple[datetime, ShortForecast | None]] = {}
        self._mid: dict[datetime, tuple[datetime, MidForecast | None]] = {}

    def _fresh(self, fetched: datetime) -> bool:
        return (self.clock() - fetched).total_seconds() < self.settings.kma_cache_s

    def _short_for(self, nx: int, ny: int) -> ShortForecast | None:
        base = short_base(self.clock())
        key = (nx, ny, base)
        with self._lock:
            hit = self._short.get(key)
            if hit is not None and self._fresh(hit[0]):
                return hit[1]
        try:
            value: ShortForecast | None = self.source.short(nx, ny, base)
        except KmaError as error:
            logger.warning("weather short_failed kind=%s", error)
            value = None
        with self._lock:
            self._short = {k: v for k, v in self._short.items() if self._fresh(v[0])}
            self._short[key] = (self.clock(), value)
        return value

    def _mid_for(self) -> MidForecast | None:
        base = mid_base(self.clock())
        with self._lock:
            hit = self._mid.get(base)
            if hit is not None and self._fresh(hit[0]):
                return hit[1]
        try:
            value: MidForecast | None = self.source.mid(base)
        except KmaError as error:
            logger.warning("weather mid_failed kind=%s", error)
            value = None
        with self._lock:
            self._mid = {base: (self.clock(), value)}
        return value

    def forecast(self, lat: float, lng: float, day: date, hour: int) -> Forecast | None:
        nx, ny = to_grid(lat, lng)
        short = self._short_for(nx, ny)
        slot = short.slots.get((day, hour)) if short is not None else None
        if short is not None and slot is not None:
            rain = slot.pty in RAIN_TYPES or (slot.pop is not None and slot.pop >= self.settings.rain_pop)
            return Forecast(
                scope="SHORT",
                issued_at=short.issued_at,
                pop=slot.pop,
                pty=slot.pty,
                sky=slot.sky,
                temp=slot.temp,
                wind=slot.wind,
                rain=rain,
            )
        mid = self._mid_for()
        middle = mid.days.get(day) if mid is not None else None
        if mid is None or middle is None:
            return None
        morning = hour < 12
        return Forecast(
            scope="MID",
            issued_at=mid.issued_at,
            pop=middle.pop_am if morning else middle.pop_pm,
            pty=None,
            sky=middle.sky_am if morning else middle.sky_pm,
            temp=None,
            wind=None,
            temp_min=middle.temp_min,
            temp_max=middle.temp_max,
        )

    def rain(self, lat: float, lng: float, day: date, hour: int) -> bool | None:
        """시간 단위 예보로 본 비 예보 여부. 단기예보가 없으면 None(판단하지 않는다)."""
        found = self.forecast(lat, lng, day, hour)
        if found is None or found.scope != "SHORT":
            return None
        return found.rain
