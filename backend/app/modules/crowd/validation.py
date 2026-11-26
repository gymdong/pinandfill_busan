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
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .estimator import GRADES
from .file_provider import FileCrowdProvider, crowd_config_from_env, crowd_dir_from_env

RHO_THRESHOLD = 0.5
AGREEMENT_THRESHOLD = 0.7
MIN_OBSERVATIONS = 30
MIN_PLACES = 3
MIN_POINTS_PER_PLACE = 5

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
class PlaceRho:
    place_id: str
    points: int  # ρ 에 쓴 (날짜, 시각) 쌍 수
    rho: float | None  # 쌍이 MIN_POINTS_PER_PLACE 미만이거나 분산 0 이면 None


@dataclass(frozen=True)
class WithinPlaceResult:
    places: list[PlaceRho]
    mean_rho: float | None
    skipped_no_hour: int  # 날짜·시각이 비어 시간대 비교에 못 쓴 행
    no_estimate: list[str] = field(default_factory=list)  # 추정이 없어 짝을 못 지은 (장소 날짜 시각)


def within_place_rho(rows: Iterable[WifiRow], estimate: EstimateLookup) -> WithinPlaceResult:
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
        rho = spearman(visitors, scores) if len(visitors) >= MIN_POINTS_PER_PLACE else None
        places.append(PlaceRho(place_id, len(visitors), rho))

    computed = [item.rho for item in places if item.rho is not None]
    mean = sum(computed) / len(computed) if computed else None
    return WithinPlaceResult(places, mean, skipped, no_estimate)


@dataclass(frozen=True)
class AgreementResult:
    compared: int  # 추정과 등급을 비교한 관측 수
    matched: int
    unavailable: list[str]  # 정보 부족(추정 없음) — 불일치로 세지 않는다
    rate: float | None


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
    return AgreementResult(compared, matched, unavailable, matched / compared if compared else None)


@dataclass(frozen=True)
class Verdict:
    rho_pass: bool | None  # None = 판정 불가
    agreement_pass: bool | None
    overall: str  # 통과 | 미달 | 판정 불가


def verdict(within: WithinPlaceResult, agreement: AgreementResult) -> Verdict:
    """둘 다 기준을 채울 때만 '통과'. 관측이 30건 미만이거나 ρ 를 낸 장소가 3곳 미만이면 통과를 주장하지 않는다."""
    computed = sum(item.rho is not None for item in within.places)
    rho_ok: bool | None = None
    if within.mean_rho is not None and computed >= MIN_PLACES:
        rho_ok = within.mean_rho >= RHO_THRESHOLD
    agree_ok: bool | None = None
    if agreement.rate is not None and agreement.compared >= MIN_OBSERVATIONS:
        agree_ok = agreement.rate >= AGREEMENT_THRESHOLD
    if rho_ok is False or agree_ok is False:
        overall = "미달"
    elif rho_ok and agree_ok:
        overall = "통과"
    else:
        overall = "판정 불가"
    return Verdict(rho_ok, agree_ok, overall)


# --- CSV 읽기 -------------------------------------------------------------------------------


def _read(path: Path) -> Iterator[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        lines = (line for line in file if line.strip() and not line.lstrip().startswith("#"))
        yield from csv.DictReader(lines)


def load_observations(path: Path) -> tuple[list[Observation], list[str]]:
    """(읽은 관측, 거절한 행 설명). 날짜·시각·등급이 올바르지 않은 행은 거절한다(값을 지어내지 않는다)."""
    rows: list[Observation] = []
    rejected: list[str] = []
    for number, raw in enumerate(_read(path), start=2):
        try:
            hour = int(raw["hour"])
            grade = raw["observed_grade"].strip()
            if not 0 <= hour <= 23 or grade not in GRADES or not raw["place_id"].strip():
                raise ValueError
            rows.append(
                Observation(
                    raw["place_id"].strip(),
                    date.fromisoformat(raw["date"].strip()),
                    hour,
                    grade,
                    (raw.get("observer") or "").strip(),
                    (raw.get("note") or "").strip(),
                )
            )
        except (KeyError, ValueError, AttributeError):
            rejected.append(f"{path.name} {number}행")
    return rows, rejected


def load_wifi(path: Path) -> tuple[list[WifiRow], list[str]]:
    """date·hour 는 비어도 된다. 방문자수가 음수·숫자 아님이거나 채워졌는데 형식이 틀린 date·hour 는 거절한다."""
    rows: list[WifiRow] = []
    rejected: list[str] = []
    for number, raw in enumerate(_read(path), start=2):
        try:
            visitors = float(raw["visitors"])
            if visitors < 0 or not math.isfinite(visitors) or not raw["place_id"].strip():
                raise ValueError
            on_date = date.fromisoformat(raw["date"].strip()) if (raw.get("date") or "").strip() else None
            hour = int(raw["hour"]) if (raw.get("hour") or "").strip() else None
            if hour is not None and not 0 <= hour <= 23:
                raise ValueError
            rows.append(WifiRow(raw["place_id"].strip(), visitors, on_date, hour))
        except (KeyError, ValueError, AttributeError):
            rejected.append(f"{path.name} {number}행")
    return rows, rejected


# --- 보고 -----------------------------------------------------------------------------------


def _fmt(value: float | None) -> str:
    return "계산 불가" if value is None else f"{value:.3f}"


def _mark(value: bool | None) -> str:
    return "판정 불가" if value is None else ("통과" if value else "미달")


def report(
    within: WithinPlaceResult,
    agreement: AgreementResult,
    result: Verdict,
    wifi_rows: int,
    observation_rows: int,
    rejected: Sequence[str],
) -> str:
    lines = [
        "AC-009 혼잡 추정 검증",
        f"입력: 와이파이 {wifi_rows}행, 관측 {observation_rows}건, 거절한 행 {len(rejected)}개",
        "",
        f"[1] Spearman ρ (장소 안 시간대 비교, 기준 평균 ≥ {RHO_THRESHOLD}, 장소별 쌍 ≥ {MIN_POINTS_PER_PLACE})",
    ]
    for item in within.places:
        lines.append(f"  {item.place_id}: 쌍 {item.points}개, ρ = {_fmt(item.rho)}")
    lines += [
        f"  평균 ρ = {_fmt(within.mean_rho)} → {_mark(result.rho_pass)} (ρ 를 낸 장소 {MIN_PLACES}곳 이상 필요)",
        f"  날짜·시각이 비어 ρ 에서 뺀 와이파이 행: {within.skipped_no_hour}개",
        "  장소 간 ρ: 계산 불가(공급자가 원점수 B×M 을 내놓지 않음)",
        "",
        f"[2] 등급 일치율 (기준 ≥ {AGREEMENT_THRESHOLD:.0%}, 비교 관측 ≥ {MIN_OBSERVATIONS}건)",
        f"  비교 {agreement.compared}건 중 일치 {agreement.matched}건, 일치율 = "
        f"{'계산 불가' if agreement.rate is None else f'{agreement.rate:.1%}'} → {_mark(result.agreement_pass)}",
        f"  정보 부족으로 비교하지 못한 관측: {len(agreement.unavailable)}건(불일치로 세지 않음)",
    ]
    if agreement.compared < MIN_OBSERVATIONS:
        lines.append(f"  경고: 비교 관측이 {MIN_OBSERVATIONS}건 미만이라 통과를 주장하지 않습니다.")
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AC-009 혼잡 추정 검증 도구")
    parser.add_argument("--observations", type=Path, required=True, help="현장 관측 CSV")
    parser.add_argument("--wifi", type=Path, required=True, help="와이파이 방문자 CSV")
    parser.add_argument("--crowd-dir", type=Path, default=None, help="혼잡 입력 디렉터리(기본 CROWD_DATA_DIR)")
    parser.add_argument("--config", type=Path, default=None, help="crowd_config.json(기본 CROWD_CONFIG_PATH)")
    args = parser.parse_args(argv)

    # 구·군 배수 M 은 장소 주소가 필요해 적용하지 않는다(B 만으로 추정). 문서에 밝혀 둔다.
    provider = FileCrowdProvider.from_dir(
        args.crowd_dir or crowd_dir_from_env(), lambda _place_id: None, args.config or crowd_config_from_env()
    )
    lookup = provider_lookup(provider)
    observations, rejected_obs = load_observations(args.observations)
    wifi, rejected_wifi = load_wifi(args.wifi)
    within = within_place_rho(wifi, lookup)
    agreement = grade_agreement(observations, lookup)
    result = verdict(within, agreement)
    print(report(within, agreement, result, len(wifi), len(observations), [*rejected_obs, *rejected_wifi]))
    return 0 if result.overall == "통과" else 1


if __name__ == "__main__":
    raise SystemExit(main())
