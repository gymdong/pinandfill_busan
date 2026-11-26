"""FR-008 날짜 배수 M 계산과 crowd_multipliers.csv 쓰기(spec R3).

M(d, 구·군) = 값(d) / 같은 구·군·같은 평일/주말의 기간 평균. 대체 상수는 없다.
- DATA-06(과거): 값 = 그날 방문자수(방문자 구분 합). 기간 = 받은 기준 기간(설정 DATA06_BASELINE_DAYS).
- DATA-07(미래): 값 = 그날 그 구·군 관광지 집중률 평균. 기간 = 받은 예측 30일.
  예측이 없는 날·구·군은 행을 만들지 않는다(→ 파일 제공자가 M 을 곱하지 않고 신호로도 세지 않는다).
값이 0 이거나 평균이 0 이면 배수를 만들지 않는다(파일 형식이 0 보다 큰 값만 받는다).

파일 쓰기: 기존 파일의 행을 읽어 같은 (date, region) 행만 새 값으로 바꾸고 나머지는 그대로 둔다
(다른 소스 행·과거 행 유지).
같은 디렉터리의 임시 파일에 쓰고 rename 하므로, 쓰기가 중간에 실패하면 기존 파일이 그대로 남는다.
기존 파일을 읽을 수 없으면(머리줄이 다름 등) 덮어쓰지 않고 예외를 낸다. 쓰는 프로세스는 배치 하나라고 본다.
"""

import csv
import os
import tempfile
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from pathlib import Path
from statistics import fmean
from typing import Literal

from .estimator import day_type
from .signals import KST, MULTIPLIER_SOURCES, MULTIPLIERS_FILE

COLUMNS = ("date", "region", "multiplier", "source", "computed_at")


def day_type_ratios(
    values: Mapping[tuple[date, str], Iterable[float]], *, combine: Literal["sum", "mean"]
) -> dict[tuple[date, str], float]:
    """(날짜, 구·군) 값 목록을 하나로 모으고(`sum`|`mean`) 같은 구·군·평일/주말 평균으로 나눈다."""
    totals: dict[tuple[date, str], float] = {}
    for key, items in values.items():
        numbers = list(items)
        if numbers:
            totals[key] = sum(numbers) if combine == "sum" else fmean(numbers)
    groups: dict[tuple[str, str], list[float]] = {}
    for (day, region), total in totals.items():
        groups.setdefault((region, day_type(day)), []).append(total)
    means = {group: fmean(items) for group, items in groups.items()}
    ratios = {}
    for (day, region), total in totals.items():
        mean = means[(region, day_type(day))]
        if total > 0 and mean > 0:
            ratios[(day, region)] = total / mean
    return ratios


def _existing_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(line for line in file if not line.lstrip().startswith("#"))
        if reader.fieldnames is None:
            return []
        if not set(COLUMNS) <= set(reader.fieldnames):
            raise ValueError(f"{path.name} 머리줄이 형식과 다릅니다")
        return [{name: (row.get(name) or "").strip() for name in COLUMNS} for row in reader]


def write_multipliers(
    directory: Path, source: str, multipliers: Mapping[tuple[date, str], float], computed_at: datetime
) -> int:
    """`source` 의 배수를 파일에 합쳐 쓰고 쓴 행 수를 돌려준다. 새 행이 없으면 파일을 건드리지 않는다."""
    if source not in MULTIPLIER_SOURCES:
        raise ValueError(f"unknown multiplier source: {source}")
    if not multipliers:
        return 0
    path = directory / MULTIPLIERS_FILE
    stamp = computed_at.astimezone(KST).isoformat(timespec="seconds")
    new_rows = {
        (day.isoformat(), region): {
            "date": day.isoformat(),
            "region": region,
            "multiplier": f"{value:.4f}",
            "source": source,
            "computed_at": stamp,
        }
        for (day, region), value in multipliers.items()
    }
    rows = [row for row in _existing_rows(path) if (row["date"], row["region"]) not in new_rows]
    rows.extend(new_rows.values())
    rows.sort(key=lambda row: (row["date"], row["region"]))

    directory.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{MULTIPLIERS_FILE}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return len(new_rows)
