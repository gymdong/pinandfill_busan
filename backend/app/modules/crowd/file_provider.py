"""FR-008 파일 기반 CrowdDataProvider. 앱 시작 시 파일을 읽고 요청마다 메모리에서 계산한다(외부 호출 없음).

운영 입력 위치는 data/crowd/(환경변수 CROWD_DATA_DIR 로 변경), 설정은 data/seed/crowd/crowd_config.json
(환경변수 CROWD_CONFIG_PATH 로 변경). 입력 파일이 없으면 모든 장소가 정보 부족이다.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from . import estimator
from .schemas import CrowdHour, CrowdSignal, PlaceCrowdResponse
from .signals import (
    KST,
    BaseSignal,
    CrowdConfig,
    CrowdInputs,
    DayType,
    HourlyValues,
    load_config,
    load_inputs,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
CROWD_DIR = REPO_ROOT / "data" / "crowd"
CROWD_CONFIG = REPO_ROOT / "data" / "seed" / "crowd" / "crowd_config.json"

# 자료 코드 → (기관, 자료 이름). SRS 데이터 목록 기준.
SOURCE_NAMES: dict[str, tuple[str, str]] = {
    "DATA-04": ("부산시 공공데이터", "행정동 생활인구(시간대)"),
    "DATA-05": ("부산교통공사", "도시철도 시간대별 승하차"),
    "DATA-06": ("공공데이터포털", "지역별 방문자수"),
    "DATA-07": ("공공데이터포털", "관광지 집중률 예측"),
}
DAY_TYPE_LABELS: dict[DayType, str] = {"WEEKDAY": "평일", "WEEKEND": "주말"}

RegionLookup = Callable[[str], str | None]


def district(address: str | None) -> str | None:
    """주소의 구·군(어느 위치든 처음 나오는 '…구'/'…군' 낱말). 예: '부산광역시 영도구 전망로 24' → '영도구'."""
    if not address:
        return None
    for token in address.split():
        if len(token) > 1 and token.endswith(("구", "군")):
            return token
    return None


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else default


def crowd_dir_from_env() -> Path:
    return _env_path("CROWD_DATA_DIR", CROWD_DIR)


def crowd_config_from_env() -> Path:
    return _env_path("CROWD_CONFIG_PATH", CROWD_CONFIG)


@dataclass(frozen=True)
class _UsedSignal:
    signal: BaseSignal
    key: str
    month: str
    values: HourlyValues


@dataclass(frozen=True)
class _PlaceProfile:
    """장소 하나의 미리 계산한 값: 쓸 수 있는 신호, B, 등급 기준 분포(B 만, 정렬)."""

    signals: tuple[_UsedSignal, ...]
    base: HourlyValues
    reference: list[float]


def _month_start(month: str) -> datetime:
    year, number = (int(part) for part in month.split("-"))
    return datetime(year, number, 1, tzinfo=KST)


def _names(code: str) -> tuple[str, str]:
    return SOURCE_NAMES.get(code, (code, code))


class FileCrowdProvider:
    """정규화 CSV 입력으로 장소·날짜의 시간대별 예상 혼잡을 계산한다."""

    def __init__(self, inputs: CrowdInputs, config: CrowdConfig, region_of: RegionLookup) -> None:
        self._inputs = inputs
        self._config = config
        self._region_of = region_of
        self._places = {
            place_id: profile for place_id in inputs.links if (profile := self._profile(place_id)) is not None
        }

    @classmethod
    def from_dir(
        cls,
        directory: Path,
        region_of: RegionLookup,
        config_path: Path = CROWD_CONFIG,
    ) -> "FileCrowdProvider":
        return cls(load_inputs(directory), load_config(config_path), region_of)

    def _profile(self, place_id: str) -> _PlaceProfile | None:
        used: list[_UsedSignal] = []
        for link in self._inputs.links.get(place_id, []):
            if link.signal not in self._config.b_weights:
                continue
            months = self._inputs.profiles.get((link.signal, link.key))
            if not months:
                continue
            month = max(months)
            values = estimator.relative(months[month])
            if values is not None:
                used.append(_UsedSignal(link.signal, link.key, month, values))
        if not used:
            return None
        base = estimator.base_profile((self._config.b_weights[item.signal], item.values) for item in used)
        return _PlaceProfile(tuple(used), base, sorted(base.values()))

    def find(self, place_id: str, on_date: date | None) -> PlaceCrowdResponse | None:
        """근거 신호가 없으면 None(→ CrowdService 가 정보 부족으로 응답)."""
        profile = self._places.get(place_id)
        if profile is None:
            return None
        visit_date = on_date if on_date is not None else datetime.now(KST).date()
        kind = estimator.day_type(visit_date)
        # 방문일의 평일/주말 칸이 하나라도 있는 신호만 근거로 센다.
        used = [item for item in profile.signals if any(slot_type == kind for slot_type, _ in item.values)]
        if not used:
            return None
        hours = sorted(hour for slot_type, hour in profile.base if slot_type == kind)

        region = self._region_of(place_id)
        multiplier = self._inputs.multipliers.get((visit_date, region)) if region is not None else None
        cutoffs = self._config.grade_percentiles
        crowd_hours = []
        for hour in hours:
            value = estimator.score(profile.base[(kind, hour)], multiplier.value if multiplier else None)
            rank = estimator.percentile(value, profile.reference)
            crowd_hours.append(CrowdHour(h=hour, grade=estimator.grade(rank, cutoffs), score=round(rank, 4)))

        signals = [self._base_signal(item, kind) for item in used]
        sources = []
        for code in dict.fromkeys(item.signal for item in used):
            org, name = _names(code)
            month = max(item.month for item in used if item.signal == code)
            sources.append(f"{org} {name} ({month} 기준)")
        as_of_values = [_month_start(item.month) for item in used]
        signal_count = len({item.signal for item in used})
        if multiplier is not None:
            org, name = _names(multiplier.source)
            sources.append(f"{org} {name} ({visit_date.isoformat()} 날짜 배수)")
            signals.append(
                CrowdSignal(
                    source=multiplier.source,
                    label=f"{name} 기반 날짜 배수",
                    ref_period=visit_date.isoformat(),
                    detail=f"{region} 날짜 배수 {multiplier.value:g}",
                )
            )
            as_of_values.append(multiplier.computed_at)
            signal_count += 1

        return PlaceCrowdResponse(
            hours=crowd_hours,
            confidence=estimator.confidence(signal_count),
            as_of=max(as_of_values),
            sources=sources,
            signals=signals,
        )

    def _base_signal(self, item: _UsedSignal, kind: DayType) -> CrowdSignal:
        _, name = _names(item.signal)
        if item.signal == "DATA-04":
            target = f"행정동 {item.key}"
        else:
            station = self._inputs.station_names.get(item.key)
            target = f"{station}({item.key})" if station else f"역 {item.key}"
        return CrowdSignal(
            source=item.signal,
            label=name,
            ref_period=item.month,
            detail=f"{target} · {DAY_TYPE_LABELS[kind]} 시간대별 상대값",
        )
