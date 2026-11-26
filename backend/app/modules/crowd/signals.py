"""FR-008 예상 혼잡의 입력 파일(정규화 CSV)과 설정 파일을 읽는다.

파일 형식은 data/crowd/README.md 에 있다. 파일이 없으면 그 신호는 비어 있고(→ 정보 부족),
깨진 행은 건너뛰고 건수만 경고로 남긴다. 값을 지어내거나 기본값으로 채우지 않는다.
`#` 로 시작하는 줄은 주석으로 보고 건너뛴다(시험용 표본 머리말 등).
"""

import csv
import json
import logging
import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, model_validator

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")

DayType = Literal["WEEKDAY", "WEEKEND"]
BaseSignal = Literal["DATA-04", "DATA-05"]
DAY_TYPES: tuple[DayType, ...] = ("WEEKDAY", "WEEKEND")
BASE_SIGNALS: tuple[BaseSignal, ...] = ("DATA-04", "DATA-05")
# 날짜 배수 M 을 추정할 수 있는 자료(DATA-06 지역별 방문자수, DATA-07 관광지 집중률)
MULTIPLIER_SOURCES = frozenset({"DATA-06", "DATA-07"})

LIVING_POPULATION_FILE = "living_population.csv"
METRO_HOURLY_FILE = "metro_hourly.csv"
MULTIPLIERS_FILE = "crowd_multipliers.csv"
LINKS_FILE = "place_signal_links.csv"

# (day_type, hour) → 값
HourlyValues = dict[tuple[DayType, int], float]


class CrowdConfig(BaseModel):
    """data/seed/crowd/crowd_config.json. 값은 AC-009 검증으로 보정할 대상이다(spec A-7)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    # 여유|보통|붐빔|매우 붐빔 을 가르는 백분위 경계 3개(오름차순, 0~1 사이)
    grade_percentiles: tuple[float, float, float]
    # 1단계 신호별 가중치
    b_weights: dict[BaseSignal, PositiveFloat] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_percentiles(self) -> "CrowdConfig":
        low, mid, high = self.grade_percentiles
        if not 0 < low < mid < high < 1:
            raise ValueError("grade_percentiles 는 0 과 1 사이의 오름차순 값 3개여야 합니다.")
        return self


def load_config(path: Path) -> CrowdConfig:
    """설정 파일이 없거나 잘못되면 앱 시작을 실패시킨다(조용히 다른 경계값을 쓰지 않는다)."""
    with path.open(encoding="utf-8") as file:
        return CrowdConfig.model_validate(json.load(file))


@dataclass(frozen=True)
class Multiplier:
    """날짜 배수 M(d, region) 한 행."""

    value: float
    source: str
    computed_at: datetime


@dataclass(frozen=True)
class SignalLink:
    """장소 → 1단계 신호 키(행정동 코드 또는 역 코드)."""

    signal: BaseSignal
    key: str


@dataclass
class CrowdInputs:
    """혼잡 계산 입력 전체. 파일이 없으면 해당 칸이 비어 있다."""

    # (신호, 키) → 기준 월(YYYY-MM) → 시간대 값
    profiles: dict[tuple[BaseSignal, str], dict[str, HourlyValues]] = field(default_factory=dict)
    station_names: dict[str, str] = field(default_factory=dict)
    # (날짜, 구·군) → 배수
    multipliers: dict[tuple[date, str], Multiplier] = field(default_factory=dict)
    links: dict[str, list[SignalLink]] = field(default_factory=dict)


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        logger.info("crowd_inputs missing file=%s", path.name)
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as file:
            lines: Iterator[str] = (line for line in file if not line.lstrip().startswith("#"))
            return [{key: (value or "").strip() for key, value in row.items() if key} for row in csv.DictReader(lines)]
    except (UnicodeDecodeError, csv.Error):
        logger.warning("crowd_inputs unreadable file=%s", path.name)
        return []


def _month(value: str) -> str:
    parsed = datetime.strptime(value, "%Y-%m")
    return parsed.strftime("%Y-%m")


def _day_type(value: str) -> DayType:
    for day_type in DAY_TYPES:
        if value == day_type:
            return day_type
    raise ValueError(value)


def _hour(value: str) -> int:
    hour = int(value)
    if not 0 <= hour <= 23:
        raise ValueError(value)
    return hour


def _count(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(value)
    return number


def _add(
    inputs: CrowdInputs, signal: BaseSignal, key: str, month: str, slot: tuple[DayType, int], value: float
) -> bool:
    """같은 (신호, 키, 월, 시간대) 행이 이미 있으면 False(앞 행을 쓴다)."""
    values = inputs.profiles.setdefault((signal, key), {}).setdefault(month, {})
    if slot in values:
        return False
    values[slot] = value
    return True


def _warn_skipped(name: str, skipped: int) -> None:
    if skipped:
        logger.warning("crowd_inputs skipped_rows file=%s count=%d", name, skipped)


def _load_living_population(inputs: CrowdInputs, directory: Path) -> None:
    skipped = 0
    for row in _rows(directory / LIVING_POPULATION_FILE):
        try:
            key = row["adm_dong_code"]
            if not key:
                raise ValueError("adm_dong_code")
            slot = (_day_type(row["day_type"]), _hour(row["hour"]))
            added = _add(inputs, "DATA-04", key, _month(row["ref_month"]), slot, _count(row["population"]))
        except (KeyError, ValueError):
            added = False
        skipped += not added
    _warn_skipped(LIVING_POPULATION_FILE, skipped)


def _load_metro(inputs: CrowdInputs, directory: Path) -> None:
    skipped = 0
    for row in _rows(directory / METRO_HOURLY_FILE):
        try:
            key = row["station_code"]
            if not key:
                raise ValueError("station_code")
            slot = (_day_type(row["day_type"]), _hour(row["hour"]))
            value = _count(row["boardings"]) + _count(row["alightings"])
            added = _add(inputs, "DATA-05", key, _month(row["ref_month"]), slot, value)
        except (KeyError, ValueError):
            added = False
        if added and row.get("station_name"):
            inputs.station_names.setdefault(key, row["station_name"])
        skipped += not added
    _warn_skipped(METRO_HOURLY_FILE, skipped)


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=KST)


def _load_multipliers(inputs: CrowdInputs, directory: Path) -> None:
    skipped = 0
    for row in _rows(directory / MULTIPLIERS_FILE):
        try:
            value = float(row["multiplier"])
            if not math.isfinite(value) or value <= 0 or not row["region"] or row["source"] not in MULTIPLIER_SOURCES:
                raise ValueError("multiplier")
            slot = (date.fromisoformat(row["date"]), row["region"])
            if slot in inputs.multipliers:
                raise ValueError("duplicate")
            inputs.multipliers[slot] = Multiplier(value, row["source"], _datetime(row["computed_at"]))
        except (KeyError, ValueError):
            skipped += 1
    _warn_skipped(MULTIPLIERS_FILE, skipped)


def _load_links(inputs: CrowdInputs, directory: Path) -> None:
    skipped = 0
    for row in _rows(directory / LINKS_FILE):
        place_id, signal, key = row.get("place_id", ""), row.get("signal", ""), row.get("key", "")
        matched = next((item for item in BASE_SIGNALS if item == signal), None)
        if not place_id or not key or matched is None:
            skipped += 1
            continue
        link = SignalLink(matched, key)
        links = inputs.links.setdefault(place_id, [])
        if link not in links:
            links.append(link)
    _warn_skipped(LINKS_FILE, skipped)


def load_inputs(directory: Path) -> CrowdInputs:
    """디렉터리의 정규화 CSV 4개를 읽는다. 디렉터리나 파일이 없으면 빈 입력이다."""
    inputs = CrowdInputs()
    _load_living_population(inputs, directory)
    _load_metro(inputs, directory)
    _load_multipliers(inputs, directory)
    _load_links(inputs, directory)
    return inputs
