"""FR-008 파일 기반 CrowdDataProvider. 앱 시작 시 파일을 읽고 요청마다 메모리에서 계산한다(외부 호출 없음).

운영 입력 위치는 data/crowd/(환경변수 CROWD_DATA_DIR 로 변경). 파일이 없으면 모든 장소가 정보 부족이다.
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
    HourlyValues,
    Multiplier,
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
DAY_TYPE_LABELS = {"WEEKDAY": "평일", "WEEKEND": "주말"}

RegionLookup = Callable[[str], str | None]


def district(address: str | None) -> str | None:
    """주소의 구·군. 예: '부산광역시 영도구 전망로 24' → '영도구'. 찾지 못하면 None."""
    if not address:
        return None
    for token in address.split()[1:]:
        if token.endswith(("구", "군")):
            return token
    return None


def crowd_dir_from_env() -> Path:
    value = os.environ.get("CROWD_DATA_DIR", "").strip()
    return Path(value) if value else CROWD_DIR


@dataclass(frozen=True)
class _UsedSignal:
    signal: BaseSignal
    key: str
    month: str
    values: HourlyValues


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

    @classmethod
    def from_dir(
        cls,
        directory: Path,
        region_of: RegionLookup,
        config_path: Path = CROWD_CONFIG,
    ) -> "FileCrowdProvider":
        return cls(load_inputs(directory), load_config(config_path), region_of)

    def _used_signals(self, place_id: str) -> list[_UsedSignal]:
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
        return used

    def _multipliers(self, region: str | None) -> dict[date, Multiplier]:
        if region is None:
            return {}
        return {day: item for (day, item_region), item in self._inputs.multipliers.items() if item_region == region}

    def find(self, place_id: str, on_date: date | None) -> PlaceCrowdResponse | None:
        """근거 신호가 없으면 None(→ CrowdService 가 정보 부족으로 응답)."""
        visit_date = on_date if on_date is not None else datetime.now(KST).date()
        used = self._used_signals(place_id)
        if not used:
            return None
        base = estimator.base_profile((self._config.b_weights[item.signal], item.values) for item in used)
        kind = estimator.day_type(visit_date)
        hours = sorted(hour for slot_type, hour in base if slot_type == kind)
        if not hours:
            return None

        region = self._region_of(place_id)
        region_multipliers = self._multipliers(region)
        multiplier = region_multipliers.get(visit_date)
        # M 은 방문일 값이 있을 때만 쓰고, 그때만 분포에도 넣는다.
        scores = estimator.distribution(
            base, {day: item.value for day, item in region_multipliers.items()} if multiplier else {}
        )
        cutoffs = self._config.grade_percentiles
        crowd_hours = []
        for hour in hours:
            value = estimator.score(base[(kind, hour)], multiplier.value if multiplier else None)
            rank = estimator.percentile(value, scores)
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

    def _base_signal(self, item: _UsedSignal, kind: str) -> CrowdSignal:
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
