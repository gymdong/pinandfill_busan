"""FR-008 날짜 배수 M 계산과 crowd_multipliers.csv 쓰기(spec R3).

M(d, 구·군) = 값(d) / 같은 구·군·같은 평일/주말의 기간 평균. 대체 상수는 없다.
- DATA-06(과거): 값 = 그날 방문자수(방문자 구분 합). 기간 = 받은 기준 기간(설정 DATA06_BASELINE_DAYS).
- DATA-07(미래): 값 = 그날 그 구·군 관광지 집중률 평균. 기간 = 받은 예측 30일.
  예측이 없는 날·구·군은 행을 만들지 않는다(→ 파일 제공자가 M 을 곱하지 않고 신호로도 세지 않는다).
값이 0 이거나 평균이 0 이면 배수를 만들지 않는다(파일 형식이 0 보다 큰 값만 받는다).
공휴일은 평일로 센다(파일 제공자와 같다, spec A-9).

파일 쓰기(`write_multipliers`):
- 같은 (date, region) 행은 새 값으로 바꾼다. 다른 소스 행은 그대로 둔다.
- `replace_since` 를 주면 그 소스의 그 날짜 이후 행을 모두 새 결과로 바꾼다(DATA-07: 새 예측에 없는 날·구·군,
  대응표에서 빠진 구·군의 옛 예측을 지운다).
- `prune_before` 를 주면 그 소스의 그 날짜 전 행을 지운다(파일이 끝없이 커지지 않게).
- 같은 디렉터리의 임시 파일에 쓰고 rename 하므로, 쓰기가 중간에 실패하면 기존 파일이 그대로 남는다.
  기존 파일을 읽을 수 없으면(머리줄이 다름 등) 덮어쓰지 않고 예외를 낸다.
- 읽기·합치기·바꾸기 동안 옆 잠금 파일(`.crowd_multipliers.csv.lock`)에 `fcntl.flock` 배타 잠금을 잡는다.
  data06·data07 이나 CLI `run` 과 `loop` 가 겹쳐도 합친 결과를 잃지 않는다. POSIX 전용(Linux·macOS, compose 이미지).
"""

import csv
import fcntl
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
LOCK_FILE = f".{MULTIPLIERS_FILE}.lock"


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


def _write_atomic(directory: Path, path: Path, rows: list[dict[str, str]]) -> None:
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


def write_multipliers(
    directory: Path,
    source: str,
    multipliers: Mapping[tuple[date, str], float],
    computed_at: datetime,
    *,
    replace_since: date | None = None,
    prune_before: date | None = None,
) -> int:
    """`source` 의 배수를 파일에 합쳐 쓰고 새로 쓴 행 수를 돌려준다. 바뀌는 것이 없으면 파일을 건드리지 않는다."""
    if source not in MULTIPLIER_SOURCES:
        raise ValueError(f"unknown multiplier source: {source}")
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
    since = replace_since.isoformat() if replace_since else None
    before = prune_before.isoformat() if prune_before else None

    def drop(row: dict[str, str]) -> bool:
        if (row["date"], row["region"]) in new_rows:
            return True
        if row["source"] != source:
            return False
        # ISO 날짜 문자열은 사전 순서가 날짜 순서와 같다.
        return (since is not None and row["date"] >= since) or (before is not None and row["date"] < before)

    directory.mkdir(parents=True, exist_ok=True)
    with (directory / LOCK_FILE).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = _existing_rows(path)
        rows = [row for row in existing if not drop(row)]
        if not new_rows and len(rows) == len(existing):
            return 0
        rows.extend(new_rows.values())
        rows.sort(key=lambda row: (row["date"], row["region"]))
        _write_atomic(directory, path, rows)
    return len(new_rows)
