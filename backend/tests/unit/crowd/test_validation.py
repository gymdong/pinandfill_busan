"""AC-009 검증 도구 시험. 값은 모두 시험용 가짜(TEST FIXTURE)이며 실제 관측·방문자수가 아니다."""

from datetime import date
from pathlib import Path

import pytest

from app.modules.crowd.validation import (
    AgreementResult,
    Observation,
    PlaceRho,
    WifiRow,
    WithinPlaceResult,
    grade_agreement,
    load_observations,
    load_wifi,
    main,
    spearman,
    verdict,
    within_place_rho,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "crowd"
DAY = date(2026, 11, 25)  # 수요일
HOURS = range(9, 18)


def test_spearman_hand_computed() -> None:
    # 순위 x=[1..5], y=[1,2,3.5,5,3.5]: 8 / sqrt(10 × 9.5) = 0.8208
    result = spearman([1, 2, 3, 4, 5], [5, 6, 7, 8, 7])
    assert result == pytest.approx(8 / 95**0.5)


def test_spearman_perfect_and_inverse() -> None:
    assert spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1.0)
    assert spearman([1, 2, 3], [30, 20, 10]) == pytest.approx(-1.0)


def test_spearman_ties_use_average_rank() -> None:
    # x 가 모두 같은 쪽이 아니면 동순위는 평균 순위: x=[1,1,2] → [1.5,1.5,3], y=[1,2,3]
    # dx=[-.5,-.5,1], dy=[-1,0,1] → sxy=1.5, sxx=1.5, syy=2 → 1.5/sqrt(3)
    assert spearman([1, 1, 2], [1, 2, 3]) == pytest.approx(1.5 / 3**0.5)


@pytest.mark.parametrize(
    ("xs", "ys"),
    [([], []), ([1], [1]), ([1, 2], [3]), ([2, 2, 2], [1, 2, 3]), ([1, 2, 3], [5, 5, 5])],
)
def test_spearman_undefined_is_none(xs: list[float], ys: list[float]) -> None:
    assert spearman(xs, ys) is None


def estimate_of(scores: dict[int, float], grade: str = "보통"):
    def lookup(place_id: str, on_date: date):
        if place_id == "NONE":
            return None
        return {hour: (score, grade) for hour, score in scores.items()}

    return lookup


def rows(place_id: str, visitors: list[float], on_date: date | None = DAY) -> list[WifiRow]:
    return [WifiRow(place_id, value, on_date, hour) for hour, value in zip(HOURS, visitors, strict=False)]


def test_within_place_rho_per_place_and_mean() -> None:
    scores = {hour: float(hour) for hour in HOURS}
    wifi = rows("A", [1, 2, 3, 4, 5, 6, 7, 8, 9]) + rows("B", [9, 8, 7, 6, 5, 4, 3, 2, 1])
    result = within_place_rho(wifi, estimate_of(scores))
    by_place = {item.place_id: item for item in result.places}
    assert by_place["A"].rho == pytest.approx(1.0)
    assert by_place["B"].rho == pytest.approx(-1.0)
    assert by_place["A"].points == 9
    assert result.mean_rho == pytest.approx(0.0)


def test_within_place_rho_skips_rows_without_date_or_hour() -> None:
    scores = {hour: float(hour) for hour in HOURS}
    wifi = [
        *rows("A", [1, 2, 3, 4, 5, 6, 7, 8, 9]),
        WifiRow("A", 100.0, None, 12),
        WifiRow("A", 100.0, DAY, None),
        WifiRow("C", 500.0),
    ]
    result = within_place_rho(wifi, estimate_of(scores))
    assert result.skipped_no_hour == 3
    assert [item.place_id for item in result.places] == ["A"]  # C 는 시간대 행이 없어 ρ 에 오르지 않는다


def test_within_place_rho_averages_duplicate_cells() -> None:
    scores = {hour: float(hour) for hour in HOURS}
    wifi = rows("A", [1, 2, 3, 4, 5, 6, 7, 8, 9]) + [WifiRow("A", 1.0, DAY, 9), WifiRow("A", 2.0, DAY, 10)]
    result = within_place_rho(wifi, estimate_of(scores))
    assert result.places[0].points == 9  # 중복 칸은 한 쌍
    assert result.places[0].rho == pytest.approx(1.0)  # 같은 값의 중복이라 평균이 그대로 → 증가


def test_within_place_rho_too_few_points_and_missing_estimate() -> None:
    scores = {hour: float(hour) for hour in HOURS}
    few = within_place_rho(rows("A", [1, 2, 3]), estimate_of(scores))
    assert few.places[0].rho is None
    assert few.mean_rho is None
    missing = within_place_rho(rows("NONE", [1, 2, 3, 4, 5, 6]), estimate_of(scores))
    assert missing.places == [PlaceRho("NONE", 0, None)]
    assert len(missing.no_estimate) == 6


def test_within_place_rho_empty_input() -> None:
    result = within_place_rho([], estimate_of({}))
    assert result == WithinPlaceResult([], None, 0, [])


def obs(place_id: str, hour: int, grade: str) -> Observation:
    return Observation(place_id, DAY, hour, grade)


def test_grade_agreement_counts_unavailable_separately() -> None:
    lookup = estimate_of({10: 0.5}, grade="붐빔")
    result = grade_agreement(
        [obs("A", 10, "붐빔"), obs("A", 10, "여유"), obs("A", 11, "붐빔"), obs("NONE", 10, "붐빔")], lookup
    )
    assert (result.compared, result.matched, result.rate) == (2, 1, 0.5)
    assert len(result.unavailable) == 2


def test_grade_agreement_empty() -> None:
    result = grade_agreement([], estimate_of({}))
    assert result == AgreementResult(0, 0, [], None)


def within_with(mean: float | None, computed: int) -> WithinPlaceResult:
    places = [PlaceRho(f"P{i}", 9, mean) for i in range(computed)]
    return WithinPlaceResult(places, mean, 0, [])


def test_verdict_passes_only_with_enough_data_and_both_criteria() -> None:
    assert verdict(within_with(0.6, 3), AgreementResult(30, 21, [], 0.7)).overall == "통과"
    assert verdict(within_with(0.4, 3), AgreementResult(30, 25, [], 25 / 30)).overall == "미달"
    assert verdict(within_with(0.9, 3), AgreementResult(30, 10, [], 1 / 3)).overall == "미달"


def test_verdict_refuses_pass_below_30_observations_or_3_places() -> None:
    few_obs = verdict(within_with(0.9, 3), AgreementResult(29, 29, [], 1.0))
    assert (few_obs.agreement_pass, few_obs.overall) == (None, "판정 불가")
    few_places = verdict(within_with(0.9, 2), AgreementResult(30, 30, [], 1.0))
    assert (few_places.rho_pass, few_places.overall) == (None, "판정 불가")
    assert verdict(within_with(None, 0), AgreementResult(0, 0, [], None)).overall == "판정 불가"


def test_load_csv_rejects_bad_rows_and_allows_empty_date_hour(tmp_path: Path) -> None:
    wifi = tmp_path / "wifi.csv"
    wifi.write_text(
        "place_id,date,hour,visitors\n"
        "A,2026-11-25,10,120\n"
        "A,,,900\n"
        "A,2026-11-25,25,5\n"
        "A,2026-13-01,10,5\n"
        "A,2026-11-25,10,-3\n",
        encoding="utf-8",
    )
    rows_, rejected = load_wifi(wifi)
    assert [(r.on_date, r.hour, r.visitors) for r in rows_] == [(DAY, 10, 120.0), (None, None, 900.0)]
    assert len(rejected) == 3

    obs_file = tmp_path / "obs.csv"
    obs_file.write_text(
        "place_id,date,hour,observed_grade,observer,note\n"
        "A,2026-11-25,10,붐빔,가짜관측자,\n"
        "A,2026-11-25,10,꽉참,가짜관측자,\n"
        "A,,10,붐빔,가짜관측자,\n",
        encoding="utf-8",
    )
    observations, rejected_obs = load_observations(obs_file)
    assert [o.observed_grade for o in observations] == ["붐빔"]
    assert len(rejected_obs) == 2


def test_header_only_templates_load_empty(tmp_path: Path) -> None:
    template_dir = Path(__file__).resolve().parents[4] / "data" / "eval" / "crowd"
    assert load_observations(template_dir / "observations_template.csv") == ([], [])
    assert load_wifi(template_dir / "wifi_visitors_template.csv") == ([], [])


def test_cli_end_to_end_with_fake_fixture(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # 2684712 는 시험용 DONG-1 에만 연결됐다. 와이파이 방문자를 같은 모양(×10)으로 두면 ρ = 1.
    population = [500, 600, 700, 800, 900, 1000, 900, 800, 700]
    wifi = tmp_path / "wifi.csv"
    wifi.write_text(
        "place_id,date,hour,visitors\n"
        + "".join(f"2684712,2026-11-25,{hour},{value * 10}\n" for hour, value in zip(HOURS, population, strict=True))
        + "2684712,,,99999\n",
        encoding="utf-8",
    )
    observations = tmp_path / "obs.csv"
    observations.write_text(
        "place_id,date,hour,observed_grade,observer,note\n2684712,2026-11-25,14,매우 붐빔,가짜,\n", encoding="utf-8"
    )
    code = main(
        [
            "--observations",
            str(observations),
            "--wifi",
            str(wifi),
            "--crowd-dir",
            str(FIXTURES),
            "--config",
            str(Path(__file__).resolve().parents[4] / "data" / "seed" / "crowd" / "crowd_config.json"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 1  # 관측 1건·장소 1곳이라 통과를 주장하지 않는다
    assert "2684712: 쌍 9개, ρ = 1.000" in out
    assert "날짜·시각이 비어 ρ 에서 뺀 와이파이 행: 1개" in out
    assert "비교 관측이 30건 미만" in out
    assert "종합: 판정 불가" in out
