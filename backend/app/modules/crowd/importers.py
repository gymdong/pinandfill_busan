"""FR-008 혼잡 원본 → 정규화 CSV 변환(data/crowd/README.md 형식).

- `metro <원본 CSV>`: 부산교통공사_시간대별 승하차인원(DATA-05, 공공데이터포털 파일, CP949 또는 UTF-8) →
  `metro_hourly.csv`. 일별 행을 (월, 역, 평일/주말, 시)별 하루 평균으로 묶는다.
  토·일은 주말, 공휴일은 평일로 센다(spec A-9).
- `living --month YYYYMM`: 부산광역시 일평균 생활인구수(행정동·시간, 통신사, DATA-04, `getDongPopTime`) →
  `living_population.csv`. 원본은 평일/주말 구분이 없는 월 일평균이라 같은 값을 WEEKDAY·WEEKEND 두 행으로 쓴다.
  population = 주거(hpopAvg) + 직장(wpopAvg) + 방문(vpopAvg) 인구.

값을 지어내지 않는다. 숫자가 아닌 칸이 있는 행은 버리고 건수를 알린다. 쓰기는 임시 파일 → rename.
"""

import argparse
import csv
import io
import os
import re
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.secrets import blank_key_is_no_key
from app.modules.crowd.file_provider import crowd_dir_from_env
from app.modules.crowd.signals import LIVING_POPULATION_FILE, METRO_HOURLY_FILE, DayType

BACKEND_DIR = Path(__file__).resolve().parents[3]
DATA04_URL = "https://apis.data.go.kr/6260000/DongPopTimeService/getDongPopTime"

METRO_FIELDS: tuple[str, ...] = (
    "ref_month",
    "station_code",
    "station_name",
    "day_type",
    "hour",
    "boardings",
    "alightings",
)
LIVING_FIELDS: tuple[str, ...] = ("ref_month", "adm_dong_code", "day_type", "hour", "population")

# 원본 머리줄 "01시-02시" → 1, "24시-01시" → 0
_METRO_HOUR = re.compile(r"^(\d{2})시-(\d{2})시$")
_LIVING_HOUR = re.compile(r"^(\d{1,2})시$")
_WEEKEND = frozenset({5, 6})


@dataclass
class Report:
    rows: int = 0
    skipped: int = 0


def _day_type(day: date) -> DayType:
    return "WEEKEND" if day.weekday() in _WEEKEND else "WEEKDAY"


def _count(value: str | None) -> int | None:
    text = (value or "").strip().replace(",", "")
    return int(text) if text.isdigit() else None


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("원본 CSV 인코딩을 알 수 없습니다(UTF-8·CP949 아님).")


def normalize_metro(text: str, *, months: int | None = 1) -> tuple[list[dict[str, Any]], Report]:
    """DATA-05 원본 CSV 문자열 → metro_hourly 행. months 는 가장 최근 몇 달만 남길지(None 이면 전부)."""
    report = Report()
    reader = csv.DictReader(io.StringIO(text))
    hour_columns = {
        column: int(match.group(1)) % 24
        for column in reader.fieldnames or ()
        if (match := _METRO_HOUR.match(column.strip()))
    }
    if len(hour_columns) != 24:
        raise ValueError("원본 머리줄에서 시간대 칸 24개('01시-02시' 형식)를 찾지 못했습니다.")
    # (월, 역번호, 평일/주말, 시) → [승차 합, 하차 합], (월, 역번호, 평일/주말) → 날짜들
    sums: dict[tuple[str, str, DayType, int], list[int]] = defaultdict(lambda: [0, 0])
    days: dict[tuple[str, str, DayType], set[date]] = defaultdict(set)
    names: dict[str, str] = {}
    for row in reader:
        try:
            day = date.fromisoformat((row.get("년월일") or "").strip())
        except ValueError:
            report.skipped += 1
            continue
        code = (row.get("역번호") or "").strip()
        kind = (row.get("구분") or "").strip()
        values = {hour: _count(row.get(column)) for column, hour in hour_columns.items()}
        if not code or kind not in ("승차", "하차") or any(v is None for v in values.values()):
            report.skipped += 1
            continue
        month = day.strftime("%Y-%m")
        day_type = _day_type(day)
        names[code] = (row.get("역명") or "").strip()
        days[(month, code, day_type)].add(day)
        slot = 0 if kind == "승차" else 1
        for hour, value in values.items():
            sums[(month, code, day_type, hour)][slot] += value or 0
    kept = sorted({key[0] for key in days}, reverse=True)
    if months is not None:
        kept = kept[:months]
    out: list[dict[str, Any]] = []
    for (month, code, day_type, hour), (boardings, alightings) in sorted(sums.items()):
        if month not in kept:
            continue
        n = len(days[(month, code, day_type)])
        out.append(
            {
                "ref_month": month,
                "station_code": code,
                "station_name": names.get(code, ""),
                "day_type": day_type,
                "hour": hour,
                "boardings": round(boardings / n, 1),
                "alightings": round(alightings / n, 1),
            }
        )
    report.rows = len(out)
    return out, report


def normalize_living(items: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], Report]:
    """DATA-04 응답 item 들 → living_population 행(WEEKDAY·WEEKEND 같은 값)."""
    report = Report()
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for item in items:
        month_raw = str(item.get("stdYm") or "").strip()
        code = str(item.get("hcode") or "").strip()
        hour_match = _LIVING_HOUR.match(str(item.get("times") or "").strip())
        parts = [_count(str(item.get(name) or "")) for name in ("hpopAvg", "wpopAvg", "vpopAvg")]
        if not re.fullmatch(r"\d{6}", month_raw) or not code or hour_match is None or any(p is None for p in parts):
            report.skipped += 1
            continue
        hour = int(hour_match.group(1))
        month = f"{month_raw[:4]}-{month_raw[4:]}"
        if not 0 <= hour <= 23 or (month, code, hour) in seen:
            report.skipped += 1
            continue
        seen.add((month, code, hour))
        population = sum(p or 0 for p in parts)
        for day_type in ("WEEKDAY", "WEEKEND"):
            row = {"ref_month": month, "adm_dong_code": code, "day_type": day_type, "hour": hour}
            out.append({**row, "population": population})
    out.sort(key=lambda r: (r["ref_month"], r["adm_dong_code"], r["day_type"], r["hour"]))
    report.rows = len(out)
    return out, report


class Data04Settings(BaseSettings):
    """DATA-04 키(공공데이터포털 일반 인증키, Decoding). 키는 출력·오류에 내지 않는다."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", extra="ignore", hide_input_in_errors=True, env_ignore_empty=True
    )

    data04_service_key: SecretStr | None = None
    public_data_timeout_s: float = 30.0

    _normalize_secret = field_validator("data04_service_key", mode="before")(blank_key_is_no_key)


def fetch_living(
    month: str, settings: Data04Settings, *, client: httpx.Client | None = None
) -> Iterator[dict[str, Any]]:
    """한 달치 item 을 모두 받는다. 응답이 정상이 아니면 실패한다(받은 일부로 파일을 쓰지 않는다)."""
    if settings.data04_service_key is None:
        raise RuntimeError("DATA04_SERVICE_KEY 가 없습니다(backend/.env).")
    key = settings.data04_service_key.get_secret_value()
    own = client is None
    http = client or httpx.Client(timeout=settings.public_data_timeout_s)
    try:
        page, received, total = 1, 0, None
        while total is None or received < total:
            params: dict[str, str | int] = {
                "serviceKey": key,
                "pageNo": page,
                "numOfRows": 1000,
                "resultType": "json",
                "stdYm": month,
            }
            try:
                response = http.get(DATA04_URL, params=params)
                body = response.json()["response"]["body"]
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                raise RuntimeError(f"DATA-04 응답이 정상이 아닙니다(page {page}, {type(error).__name__}).") from None
            batch = (body.get("items") or {}).get("item") or []
            batch = [batch] if isinstance(batch, dict) else batch
            total = int(body.get("totalCount") or 0)
            if not batch:
                break
            yield from batch
            received += len(batch)
            page += 1
        if total == 0 or received < total:
            raise RuntimeError(f"DATA-04 {month} 자료가 없거나 덜 받았습니다({received}/{total}).")
    finally:
        if own:
            http.close()


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.modules.crowd.importers", description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=None, help="기본: CROWD_DATA_DIR 또는 data/crowd")
    sub = parser.add_subparsers(dest="command", required=True)
    metro = sub.add_parser("metro", help="DATA-05 원본 CSV → metro_hourly.csv")
    metro.add_argument("source", type=Path)
    metro.add_argument("--months", type=int, default=1, help="최근 몇 달만 남길지(0 이면 전부)")
    living = sub.add_parser("living", help="DATA-04 API → living_population.csv")
    living.add_argument("--month", required=True, help="기준년월 YYYYMM")
    args = parser.parse_args(argv)
    out_dir: Path = args.out_dir or crowd_dir_from_env()

    if args.command == "metro":
        rows, report = normalize_metro(_decode(args.source.read_bytes()), months=args.months or None)
        target = out_dir / METRO_HOURLY_FILE
        fields = METRO_FIELDS
    else:
        if not re.fullmatch(r"\d{6}", args.month):
            parser.error("--month 는 YYYYMM 입니다.")
        try:
            rows, report = normalize_living(fetch_living(args.month, Data04Settings()))
        except RuntimeError as error:
            print(f"실패: {error}", file=sys.stderr)
            return 1
        target = out_dir / LIVING_POPULATION_FILE
        fields = LIVING_FIELDS
    if not rows:
        print("실패: 쓸 수 있는 행이 없습니다. 파일은 그대로입니다.", file=sys.stderr)
        return 1
    write_csv(target, fields, rows)
    print(f"{target}: {report.rows}행 씀, 버린 원본 행 {report.skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
