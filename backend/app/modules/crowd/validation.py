"""AC-009 검증 도구: 와이파이 방문자 순위와 우리 추정의 Spearman ρ, 현장 관측 등급 일치율.

도구만 만든다. 데이터(관측 30건·와이파이 방문자)는 팀이 data/eval/crowd/ 양식에 채운다(README 참고).
실행: `uv run python -m app.modules.crowd.validation --observations 관측.csv --wifi 와이파이.csv`

우리 점수는 장소별 백분위(0~1)라 장소끼리 크기를 비교할 수 없다. 그래서 ρ 는 장소마다 시간대 사이에서
구하고(within-place) 장소별 ρ 의 평균을 쓴다. 공급자가 원점수(B×M)를 내놓지 않아 장소 간 ρ 는 계산하지 않는다.
날짜·시간이 빈 와이파이 행은 시간대별 비교에 쓸 수 없어 ρ 에서 빼고 건수만 센다.
"""

import argparse
import csv
import math
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import NoReturn

from app.modules.places.samples import SamplePlaceData, load_sample_places

from .estimator import GRADES
from .file_provider import FileCrowdProvider, RegionLookup, crowd_config_from_env, crowd_dir_from_env, district

RHO_THRESHOLD = 0.5
MIN_PLACE_RHO = 0.0  # 장소별 ρ 가 이 값 미만인 장소가 하나라도 있으면 평균이 높아도 미달
AGREEMENT_THRESHOLD = 0.7
MIN_OBSERVATIONS = 30
MIN_PLACES = 3
MIN_POINTS_PER_PLACE = 5
TARGET_PLACE_NAMES = ("흰여울문화마을", "봉래물양장", "감지해변")  # 영도구 공공 와이파이 3곳(AC-009)

EXIT_CODES = {"통과": 0, "미달": 1, "판정 불가": 2}
EXIT_INPUT_ERROR = 3

# 장소·날짜 → {시각: (백분위 score, 등급)}. 근거 신호가 없으면 None(정보 부족).
HourlyEstimate = Mapping[int, tuple[float, str]]
EstimateLookup = Callable[[str, date], HourlyEstimate | None]


@dataclass(frozen=True)
class Observation:
    place_id: str
    on_date: date
    hour: int
    observed_grade: str
    observer: str = ""
    note: str = ""


@dataclass(frozen=True)
class WifiRow:
    place_id: str
    visitors: float
    on_date: date | None = None
    hour: int | None = None


def _ranks(values: Sequence[float]) -> list[float]:
    """동순위는 평균 순위(1부터)."""
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        for index in order[start : end + 1]:
            ranks[index] = (start + end) / 2 + 1
        start = end + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """평균 순위의 피어슨 상관. 길이가 다르거나 n<2 이거나 한쪽 분산이 0 이면 None."""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    return sxy / math.sqrt(sxx * syy)


@dataclass(frozen=True)
class Criteria:
    """표본 크기 기준. 기본값은 AC-009 와 이 도구의 최소 표본 규칙이다."""

    min_observations: int = MIN_OBSERVATIONS
    min_places: int = MIN_PLACES
    min_points: int = MIN_POINTS_PER_PLACE


DEFAULT_CRITERIA = Criteria()


@dataclass(frozen=True)
class PlaceRho:
    place_id: str
    points: int  # ρ 에 쓴 (날짜, 시각) 쌍 수
    rho: float | None  # 쌍이 min_points 미만이거나 분산 0 이면 None


@dataclass(frozen=True)
class WithinPlaceResult:
    places: list[PlaceRho]
    mean_rho: float | None
    skipped_no_hour: int  # 날짜·시각이 비어 시간대 비교에 못 쓴 행
    no_estimate: list[str] = field(default_factory=list)  # 추정이 없어 짝을 못 지은 (장소 날짜 시각)

    @property
    def min_rho(self) -> float | None:
        values = [item.rho for item in self.places if item.rho is not None]
        return min(values) if values else None


def within_place_rho(
    rows: Iterable[WifiRow], estimate: EstimateLookup, min_points: int = MIN_POINTS_PER_PLACE
) -> WithinPlaceResult:
    """장소마다 같은 (날짜, 시각) 의 방문자수 vs 백분위 score 의 ρ. 같은 칸의 중복 행은 평균한다."""
    cells: dict[str, dict[tuple[date, int], list[float]]] = {}
    skipped = 0
    for row in rows:
        if row.on_date is None or row.hour is None:
            skipped += 1
            continue
        cells.setdefault(row.place_id, {}).setdefault((row.on_date, row.hour), []).append(row.visitors)

    places: list[PlaceRho] = []
    no_estimate: list[str] = []
    for place_id, by_cell in sorted(cells.items()):
        visitors: list[float] = []
        scores: list[float] = []
        for (on_date, hour), values in sorted(by_cell.items()):
            hours = estimate(place_id, on_date)
            if hours is None or hour not in hours:
                no_estimate.append(f"{place_id} {on_date.isoformat()} {hour}시")
                continue
            visitors.append(sum(values) / len(values))
            scores.append(hours[hour][0])
        rho = spearman(visitors, scores) if len(visitors) >= min_points else None
        places.append(PlaceRho(place_id, len(visitors), rho))

    computed = [item.rho for item in places if item.rho is not None]
    mean = sum(computed) / len(computed) if computed else None
    return WithinPlaceResult(places, mean, skipped, no_estimate)


@dataclass(frozen=True)
class AgreementResult:
    compared: int  # 추정과 등급을 비교한 관측 수
    matched: int
    unavailable: list[str]  # 정보 부족(추정 없음)
    rate: float | None  # 느슨한 일치율: 정보 부족 제외(참고용)
    strict_rate: float | None = None  # 엄격한 일치율: 정보 부족을 불일치로 센다(판정에 쓴다)

    @property
    def total(self) -> int:
        return self.compared + len(self.unavailable)


def grade_agreement(observations: Iterable[Observation], estimate: EstimateLookup) -> AgreementResult:
    compared = matched = 0
    unavailable: list[str] = []
    for obs in observations:
        hours = estimate(obs.place_id, obs.on_date)
        if hours is None or obs.hour not in hours:
            unavailable.append(f"{obs.place_id} {obs.on_date.isoformat()} {obs.hour}시")
            continue
        compared += 1
        matched += hours[obs.hour][1] == obs.observed_grade
    total = compared + len(unavailable)
    return AgreementResult(
        compared, matched, unavailable, matched / compared if compared else None, matched / total if total else None
    )


@dataclass(frozen=True)
class Verdict:
    rho_pass: bool | None  # None = 판정 불가
    agreement_pass: bool | None
    overall: str  # 통과 | 미달 | 판정 불가


def verdict(within: WithinPlaceResult, agreement: AgreementResult, criteria: Criteria = DEFAULT_CRITERIA) -> Verdict:
    """둘 다 기준을 채울 때만 '통과'.

    ρ: 평균 ≥ 0.5 이고 ρ 를 낸 모든 장소가 0 이상(평균이 한 장소의 음의 상관을 가리지 못하게).
    ρ 를 낸 장소가 criteria.min_places 미만이면 판정 불가.
    일치율: 정보 부족을 불일치로 센 엄격한 일치율 ≥ 70%. 관측이 criteria.min_observations 건 미만이면 판정 불가.
    """
    computed = sum(item.rho is not None for item in within.places)
    rho_ok: bool | None = None
    if within.mean_rho is not None and within.min_rho is not None and computed >= criteria.min_places:
        rho_ok = within.mean_rho >= RHO_THRESHOLD and within.min_rho >= MIN_PLACE_RHO
    agree_ok: bool | None = None
    if agreement.strict_rate is not None and agreement.total >= criteria.min_observations:
        agree_ok = agreement.strict_rate >= AGREEMENT_THRESHOLD
    if rho_ok is False or agree_ok is False:
        overall = "미달"
    elif rho_ok and agree_ok:
        overall = "통과"
    else:
        overall = "판정 불가"
    return Verdict(rho_ok, agree_ok, overall)


# --- CSV 읽기 -------------------------------------------------------------------------------


class InputError(Exception):
    """입력 파일·옵션이 잘못돼 계산을 시작할 수 없다(종료 코드 3)."""


def _read(path: Path, required: Sequence[str], optional: Sequence[str]) -> Iterator[tuple[int, dict[str, str] | str]]:
    """(실제 파일 줄 번호, 행 dict 또는 거절 사유). 빈 줄·`#` 주석 줄은 건너뛰되 줄 번호는 센다."""
    try:
        file = path.open(encoding="utf-8-sig", newline="")
    except OSError as error:
        raise InputError(f"{path} 를 열 수 없습니다: {error.strerror or error}") from error
    with file:
        reader = csv.reader(file)
        header: list[str] | None = None
        try:
            for row in reader:
                if not row or not any(cell.strip() for cell in row) or row[0].lstrip().startswith("#"):
                    continue
                if header is None:
                    header = [cell.strip() for cell in row]
                    missing = [name for name in required if name not in header]
                    unknown = [name for name in header if name not in (*required, *optional)]
                    if missing or unknown:
                        raise InputError(
                            f"{path.name} {reader.line_num}행 머리줄 오류: "
                            f"없는 열 {missing or '없음'}, 모르는 열 {unknown or '없음'}"
                        )
                    continue
                if len(row) != len(header):
                    relation = "많음" if len(row) > len(header) else "적음"
                    yield reader.line_num, f"열이 머리줄보다 {relation}({len(row)}개, 머리줄 {len(header)}개)"
                else:
                    yield reader.line_num, dict(zip(header, (cell.strip() for cell in row), strict=True))
        except (UnicodeDecodeError, csv.Error) as error:
            raise InputError(f"{path.name} 를 읽을 수 없습니다: {error}") from error
    if header is None:
        raise InputError(f"{path.name} 에 머리줄이 없습니다. 필요한 열: {list(required)}")


def load_observations(path: Path) -> tuple[list[Observation], list[str]]:
    """(읽은 관측, 거절한 행 설명). 날짜·시각·등급이 올바르지 않은 행은 거절한다(값을 지어내지 않는다)."""
    rows: list[Observation] = []
    rejected: list[str] = []
    for number, raw in _read(path, ("place_id", "date", "hour", "observed_grade"), ("observer", "note")):
        if isinstance(raw, str):
            rejected.append(f"{path.name} {number}행: {raw}")
            continue
        try:
            hour = int(raw["hour"])
            if not 0 <= hour <= 23:
                raise ValueError("hour 는 0~23")
            if raw["observed_grade"] not in GRADES:
                raise ValueError("observed_grade 는 여유/보통/붐빔/매우 붐빔")
            if not raw["place_id"]:
                raise ValueError("place_id 가 비어 있음")
            rows.append(
                Observation(
                    raw["place_id"],
                    date.fromisoformat(raw["date"]),
                    hour,
                    raw["observed_grade"],
                    raw.get("observer", ""),
                    raw.get("note", ""),
                )
            )
        except ValueError as error:
            rejected.append(f"{path.name} {number}행: {error}")
    return rows, rejected


def load_wifi(path: Path) -> tuple[list[WifiRow], list[str]]:
    """date·hour 는 비어도 된다. 방문자수가 음수·숫자 아님이거나 채워졌는데 형식이 틀린 date·hour 는 거절한다."""
    rows: list[WifiRow] = []
    rejected: list[str] = []
    for number, raw in _read(path, ("place_id", "date", "hour", "visitors"), ()):
        if isinstance(raw, str):
            rejected.append(f"{path.name} {number}행: {raw}")
            continue
        try:
            visitors = float(raw["visitors"])
            if visitors < 0 or not math.isfinite(visitors):
                raise ValueError("visitors 는 0 이상 숫자")
            if not raw["place_id"]:
                raise ValueError("place_id 가 비어 있음")
            on_date = date.fromisoformat(raw["date"]) if raw["date"] else None
            hour = int(raw["hour"]) if raw["hour"] else None
            if hour is not None and not 0 <= hour <= 23:
                raise ValueError("hour 는 0~23")
            rows.append(WifiRow(raw["place_id"], visitors, on_date, hour))
        except ValueError as error:
            rejected.append(f"{path.name} {number}행: {error}")
    return rows, rejected


# --- 보고 -----------------------------------------------------------------------------------


def _fmt(value: float | None) -> str:
    return "계산 불가" if value is None else f"{value:.3f}"


def _pct(value: float | None) -> str:
    return "계산 불가" if value is None else f"{value:.1%}"


def _mark(value: bool | None) -> str:
    return "판정 불가" if value is None else ("통과" if value else "미달")


def report(
    within: WithinPlaceResult,
    agreement: AgreementResult,
    result: Verdict,
    wifi_rows: int,
    observation_rows: int,
    rejected: Sequence[str],
    criteria: Criteria = DEFAULT_CRITERIA,
) -> str:
    lines = [
        "AC-009 혼잡 추정 검증",
        f"입력: 와이파이 {wifi_rows}행, 관측 {observation_rows}건, 거절한 행 {len(rejected)}개",
        "",
        f"[1] Spearman ρ (장소 안 시간대 비교, 평균 ≥ {RHO_THRESHOLD} 그리고 장소별 최소 ≥ {MIN_PLACE_RHO:g}, "
        f"장소별 쌍 ≥ {criteria.min_points})",
    ]
    for item in within.places:
        lines.append(f"  {item.place_id}: 쌍 {item.points}개, ρ = {_fmt(item.rho)}")
    lines += [
        f"  평균 ρ = {_fmt(within.mean_rho)}, 최소 ρ = {_fmt(within.min_rho)} → {_mark(result.rho_pass)} "
        f"(ρ 를 낸 장소 {criteria.min_places}곳 이상 필요)",
        f"  날짜·시각이 비어 ρ 에서 뺀 와이파이 행: {within.skipped_no_hour}개",
        "  장소 간 ρ: 계산 불가(공급자가 원점수 B×M 을 내놓지 않음)",
        "",
        f"[2] 등급 일치율 (엄격한 일치율 ≥ {AGREEMENT_THRESHOLD:.0%}, 관측 ≥ {criteria.min_observations}건)",
        f"  관측 {agreement.total}건: 비교 {agreement.compared}건 중 일치 {agreement.matched}건, "
        f"정보 부족 {len(agreement.unavailable)}건",
        f"  엄격한 일치율(정보 부족=불일치) = {_pct(agreement.strict_rate)} → {_mark(result.agreement_pass)}",
        f"  참고: 정보 부족 제외 일치율 = {_pct(agreement.rate)}",
    ]
    if agreement.total < criteria.min_observations:
        lines.append(f"  경고: 관측이 {criteria.min_observations}건 미만이라 통과를 주장하지 않습니다.")
    unpaired = [*within.no_estimate, *agreement.unavailable, *rejected]
    if unpaired:
        lines += ["", "[3] 짝을 못 지었거나 거절한 행"]
        lines += [f"  - {text}" for text in unpaired]
    lines += ["", f"종합: {result.overall}"]
    return "\n".join(lines)


def provider_lookup(provider: FileCrowdProvider) -> EstimateLookup:
    def lookup(place_id: str, on_date: date) -> HourlyEstimate | None:
        response = provider.find(place_id, on_date)
        if response is None:
            return None
        return {
            item.h: (item.score, item.grade)
            for item in response.hours
            if item.score is not None and item.grade is not None
        }

    return lookup


def region_lookup(places: SamplePlaceData) -> RegionLookup:
    """app.main.default_crowd_service 와 같은 방식: 장소 주소의 구·군."""

    def region_of(place_id: str) -> str | None:
        item = places.place(place_id)
        return district(item.address) if item is not None else None

    return region_of


def default_place_ids(places: SamplePlaceData) -> list[str]:
    """표본에서 이름으로 찾은 영도구 와이파이 3곳의 id. 하나라도 없으면 직접 지정해야 한다."""
    by_name = {item.place.name: item.place.id for item in places.all()}
    missing = [name for name in TARGET_PLACE_NAMES if name not in by_name]
    if missing:
        raise InputError(
            f"표본 장소에 {', '.join(missing)} 이(가) 없어 기본 장소를 정할 수 없습니다. "
            "--places 로 place_id 를 직접 지정하세요."
        )
    return [by_name[name] for name in TARGET_PLACE_NAMES]


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        print(f"{self.prog}: {message}", file=sys.stderr)
        raise SystemExit(EXIT_INPUT_ERROR)


def _run(args: argparse.Namespace) -> int:
    places = load_sample_places()
    place_ids = set(args.places if args.places else default_place_ids(places))
    provider = FileCrowdProvider.from_dir(
        args.crowd_dir or crowd_dir_from_env(), region_lookup(places), args.config or crowd_config_from_env()
    )
    lookup = provider_lookup(provider)
    observations, rejected_obs = load_observations(args.observations)
    wifi, rejected_wifi = load_wifi(args.wifi)
    observations = [item for item in observations if item.place_id in place_ids]
    wifi = [item for item in wifi if item.place_id in place_ids]
    criteria = Criteria(args.min_observations, args.min_places, args.min_points)
    within = within_place_rho(wifi, lookup, criteria.min_points)
    agreement = grade_agreement(observations, lookup)
    result = verdict(within, agreement, criteria)
    rejected = [*rejected_obs, *rejected_wifi]
    print(report(within, agreement, result, len(wifi), len(observations), rejected, criteria))
    return EXIT_CODES[result.overall]


def main(argv: Sequence[str] | None = None) -> int:
    parser = _Parser(description="AC-009 혼잡 추정 검증 도구. 종료 코드: 0 통과, 1 미달, 2 판정 불가, 3 입력 오류")
    parser.add_argument("--observations", type=Path, required=True, help="현장 관측 CSV")
    parser.add_argument("--wifi", type=Path, required=True, help="와이파이 방문자 CSV")
    parser.add_argument("--crowd-dir", type=Path, default=None, help="혼잡 입력 디렉터리(기본 CROWD_DATA_DIR)")
    parser.add_argument("--config", type=Path, default=None, help="crowd_config.json(기본 CROWD_CONFIG_PATH)")
    parser.add_argument(
        "--places",
        nargs="+",
        default=None,
        help="검증할 place_id. 기본은 표본에서 이름으로 찾은 흰여울문화마을·봉래물양장·감지해변(하나라도 없으면 필수)",
    )
    parser.add_argument("--min-observations", type=int, default=MIN_OBSERVATIONS, help="필요한 관측 수(기본 30)")
    parser.add_argument("--min-places", type=int, default=MIN_PLACES, help="ρ 를 내야 하는 장소 수(기본 3)")
    parser.add_argument("--min-points", type=int, default=MIN_POINTS_PER_PLACE, help="장소별 필요한 쌍 수(기본 5)")
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except (InputError, OSError, ValueError) as error:  # ValueError: 설정 JSON·스키마 오류 포함
        print(f"입력 오류: {error}", file=sys.stderr)
        return EXIT_INPUT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
