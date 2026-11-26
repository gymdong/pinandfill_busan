"""AC-009 검증 도구 시험. 값은 모두 시험용 가짜(TEST FIXTURE)이며 실제 관측·방문자수가 아니다."""

from datetime import date
from pathlib import Path

import pytest

from app.modules.crowd.estimator import GRADES
from app.modules.crowd.file_provider import FileCrowdProvider
from app.modules.crowd.validation import (
    AgreementResult,
    Criteria,
    InputError,
    Observation,
    PlaceRho,
    WifiRow,
    WithinPlaceResult,
    grade_agreement,
    load_observations,
    load_wifi,
    main,
    partition_by_places,
    provider_lookup,
    region_lookup,
    spearman,
    verdict,
    within_place_rho,
)
from app.modules.places.samples import load_sample_places

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


def agree(compared: int, matched: int, unavailable: int = 0) -> AgreementResult:
    total = compared + unavailable
    return AgreementResult(
        compared,
        matched,
        ["정보 부족"] * unavailable,
        matched / compared if compared else None,
        matched / total if total else None,
    )


def test_grade_agreement_counts_unavailable_separately_and_strictly() -> None:
    lookup = estimate_of({10: 0.5}, grade="붐빔")
    result = grade_agreement(
        [obs("A", 10, "붐빔"), obs("A", 10, "여유"), obs("A", 11, "붐빔"), obs("NONE", 10, "붐빔")], lookup
    )
    assert (result.compared, result.matched, result.rate) == (2, 1, 0.5)
    assert len(result.unavailable) == 2
    assert result.strict_rate == 0.25  # 정보 부족 2건도 분모에 넣는다


def test_grade_agreement_empty() -> None:
    result = grade_agreement([], estimate_of({}))
    assert result == AgreementResult(0, 0, [], None, None)


def within_with(rhos: list[float | None]) -> WithinPlaceResult:
    places = [PlaceRho(f"P{i}", 9, rho) for i, rho in enumerate(rhos)]
    values = [rho for rho in rhos if rho is not None]
    return WithinPlaceResult(places, sum(values) / len(values) if values else None, 0, [])


def test_verdict_passes_only_with_enough_data_and_both_criteria() -> None:
    assert verdict(within_with([0.6, 0.6, 0.6]), agree(30, 21)).overall == "통과"
    assert verdict(within_with([0.4, 0.4, 0.4]), agree(30, 25)).overall == "미달"
    assert verdict(within_with([0.9, 0.9, 0.9]), agree(30, 10)).overall == "미달"


def test_verdict_one_negative_place_fails_even_if_mean_passes() -> None:
    within = within_with([0.9, 0.9, -0.1])
    assert within.mean_rho == pytest.approx(17 / 30)
    assert verdict(within, agree(30, 30)).overall == "미달"


def test_verdict_uses_strict_agreement_rate() -> None:
    # 비교한 20건은 모두 일치(느슨 100%)지만 정보 부족 10건을 불일치로 세면 20/30 = 66.7% 라 미달
    result = verdict(within_with([0.9, 0.9, 0.9]), agree(20, 20, unavailable=10))
    assert (result.agreement_pass, result.overall) == (False, "미달")


def test_verdict_refuses_pass_below_30_observations_or_3_places() -> None:
    few_obs = verdict(within_with([0.9, 0.9, 0.9]), agree(29, 29))
    assert (few_obs.agreement_pass, few_obs.overall) == (None, "판정 불가")
    few_places = verdict(within_with([0.9, 0.9]), agree(30, 30))
    assert (few_places.rho_pass, few_places.overall) == (None, "판정 불가")
    assert verdict(within_with([]), agree(0, 0)).overall == "판정 불가"


def test_verdict_criteria_are_adjustable() -> None:
    relaxed = Criteria(min_observations=10, min_places=2, min_points=5)
    assert verdict(within_with([0.9, 0.9]), agree(10, 10), relaxed).overall == "통과"


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


def test_rejected_rows_report_actual_file_line_numbers(tmp_path: Path) -> None:
    wifi = tmp_path / "wifi.csv"
    wifi.write_text(
        "# 주석\n\nplace_id,date,hour,visitors\nA,2026-11-25,10,120\n\nA,2026-11-25,10,abc\n\nA,2026-11-25,10,1,9\n",
        encoding="utf-8",
    )
    rows_, rejected = load_wifi(wifi)
    assert len(rows_) == 1
    assert rejected[0].startswith("wifi.csv 6행: ")  # 빈 줄·주석 줄도 센 실제 줄 번호
    assert rejected[1].startswith("wifi.csv 8행: 열이 머리줄보다 많음")


def test_header_errors_are_reported(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    missing.write_text("place_id,date,hour\nA,2026-11-25,10\n", encoding="utf-8")
    with pytest.raises(InputError, match="없는 열 \\['visitors'\\]"):
        load_wifi(missing)
    unknown = tmp_path / "unknown.csv"
    unknown.write_text("place_id,date,hour,visitors,extra\n", encoding="utf-8")
    with pytest.raises(InputError, match="모르는 열 \\['extra'\\]"):
        load_wifi(unknown)
    empty = tmp_path / "empty.csv"
    empty.write_text("# 주석만\n", encoding="utf-8")
    with pytest.raises(InputError, match="머리줄이 없습니다"):
        load_wifi(empty)
    with pytest.raises(InputError, match="열 수 없습니다"):
        load_wifi(tmp_path / "nope.csv")


def test_header_only_templates_load_empty() -> None:
    template_dir = Path(__file__).resolve().parents[4] / "data" / "eval" / "crowd"
    assert load_observations(template_dir / "observations_template.csv") == ([], [])
    assert load_wifi(template_dir / "wifi_visitors_template.csv") == ([], [])


def test_multiplier_is_applied_like_production() -> None:
    # 흰여울문화마을(2684712)은 표본 주소가 영도구라, 가짜 M 파일(2026-11-25 영도구 0.8)이 적용돼야 한다.
    places = load_sample_places()
    region_of = region_lookup(places)
    assert region_of("2684712") == "영도구"
    with_m = provider_lookup(FileCrowdProvider.from_dir(FIXTURES, region_of))("2684712", DAY)
    without_m = provider_lookup(FileCrowdProvider.from_dir(FIXTURES, lambda _id: None))("2684712", DAY)
    assert with_m is not None
    assert without_m is not None
    assert {h: v[0] for h, v in with_m.items()} != {h: v[0] for h, v in without_m.items()}


def run_cli(tmp_path: Path, *extra: str, obs_rows: str = "", wifi_rows: str = "") -> int:
    observations = tmp_path / "obs.csv"
    observations.write_text("place_id,date,hour,observed_grade,observer,note\n" + obs_rows, encoding="utf-8")
    wifi = tmp_path / "wifi.csv"
    wifi.write_text("place_id,date,hour,visitors\n" + wifi_rows, encoding="utf-8")
    return main(["--observations", str(observations), "--wifi", str(wifi), "--crowd-dir", str(FIXTURES), *extra])


def test_cli_end_to_end_with_fake_fixture(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # 2684712 는 시험용 DONG-1 에만 연결됐다. 와이파이 방문자를 같은 모양(×10)으로 두면 ρ 가 거의 1.
    population = [500, 600, 700, 800, 900, 1000, 900, 800, 700]
    wifi_rows = "".join(
        f"2684712,2026-11-25,{hour},{value * 10}\n" for hour, value in zip(HOURS, population, strict=True)
    )
    code = run_cli(
        tmp_path,
        "--places",
        "2684712",
        obs_rows="2684712,2026-11-25,14,매우 붐빔,가짜,\n",
        wifi_rows=wifi_rows + "2684712,,,99999\n9999,2026-11-25,10,5\n",
    )
    out = capsys.readouterr().out
    assert code == 2  # 관측 1건·장소 1곳이라 통과를 주장하지 않는다(판정 불가)
    assert "2684712: 쌍 9개, ρ = 0.99" in out  # M=0.8 이 일부 시간대를 백분위 0 으로 눌러 1 에서 약간 벗어난다
    assert "와이파이: 어느 장소인지 알 수 없는 place_id(오타 의심) — 9999" in out  # 걸러내되 보고한다
    assert "날짜·시각이 비어 ρ 에서 뺀 와이파이 행: 1개" in out
    assert "관측이 30건 미만" in out
    assert "종합: 판정 불가" in out


def test_cli_exit_codes_for_pass_and_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    population = [500, 600, 700, 800, 900, 1000, 900, 800, 700]
    wifi_rows = "".join(f"2684712,2026-11-25,{h},{v}\n" for h, v in zip(HOURS, population, strict=True))
    estimate = provider_lookup(FileCrowdProvider.from_dir(FIXTURES, region_lookup(load_sample_places())))
    hours = estimate("2684712", DAY)
    assert hours is not None
    actual = hours[14][1]
    other = next(grade for grade in GRADES if grade != actual)
    options = ("--places", "2684712", "--min-observations", "1", "--min-places", "1")
    assert run_cli(tmp_path, *options, obs_rows=f"2684712,2026-11-25,14,{actual},가짜,\n", wifi_rows=wifi_rows) == 0
    assert "종합: 통과" in capsys.readouterr().out
    assert run_cli(tmp_path, *options, obs_rows=f"2684712,2026-11-25,14,{other},가짜,\n", wifi_rows=wifi_rows) == 1
    assert "종합: 미달" in capsys.readouterr().out


def test_cli_input_errors_exit_3_without_traceback(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # 기본 장소(봉래물양장·감지해변)가 표본에 없으면 --places 가 필요하다.
    assert run_cli(tmp_path) == 3
    assert "--places" in capsys.readouterr().err
    (tmp_path / "bad.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    code = main(["--observations", str(tmp_path / "bad.csv"), "--wifi", str(tmp_path / "bad.csv"), "--places", "x"])
    assert code == 3
    assert "입력 오류" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exited:  # 필수 옵션 누락
        main(["--wifi", "x"])
    assert exited.value.code == 3
    capsys.readouterr()


def test_partition_separates_known_outside_and_unknown_places() -> None:
    rows = [obs("A", 9, "붐빔"), obs("B", 9, "붐빔"), obs("TYPO", 9, "붐빔"), obs("TYPO", 10, "붐빔")]
    part = partition_by_places(rows, lambda item: item.place_id, {"A"}, {"A", "B"})
    assert [item.place_id for item in part.kept] == ["A"]
    assert (part.outside, part.unknown, part.dropped_rows) == (["B"], ["TYPO"], 3)


def test_cli_unknown_observation_place_forces_undecidable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    population = [500, 600, 700, 800, 900, 1000, 900, 800, 700]
    wifi_rows = "".join(f"2684712,2026-11-25,{h},{v}\n" for h, v in zip(HOURS, population, strict=True))
    estimate = provider_lookup(FileCrowdProvider.from_dir(FIXTURES, region_lookup(load_sample_places())))
    hours = estimate("2684712", DAY)
    assert hours is not None
    options = ("--places", "2684712", "--min-observations", "1", "--min-places", "1")
    good = f"2684712,2026-11-25,14,{hours[14][1]},가짜,\n"
    # 오타 행이 없으면 통과(0), 있으면 같은 입력이라도 판정 불가(2)
    assert run_cli(tmp_path, *options, obs_rows=good, wifi_rows=wifi_rows) == 0
    capsys.readouterr()
    code = run_cli(tmp_path, *options, obs_rows=good + "TYPO,2026-11-25,14,붐빔,가짜,\n", wifi_rows=wifi_rows)
    out = capsys.readouterr().out
    assert code == 2
    assert "오타 의심) — TYPO" in out
    assert "종합: 판정 불가" in out


def test_cli_known_place_outside_places_is_only_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = run_cli(
        tmp_path,
        "--places",
        "2684712",
        obs_rows="126658,2026-11-25,14,붐빔,가짜,\n",
        wifi_rows="126658,2026-11-25,10,5\n",  # 태종대: 표본에 있지만 --places 밖
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "관측: --places 밖 장소의 행을 뺌 — 126658" in out
    assert "와이파이: --places 밖 장소의 행을 뺌 — 126658" in out
    assert "오타 의심" not in out


@pytest.mark.parametrize("option", ["--min-observations", "--min-places", "--min-points"])
@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_cli_rejects_min_options_below_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], option: str, value: str
) -> None:
    with pytest.raises(SystemExit) as exited:
        run_cli(tmp_path, "--places", "2684712", option, value)
    assert exited.value.code == 3
    assert option in capsys.readouterr().err


def test_cli_broken_config_is_input_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "config.json"
    bad.write_text("{not json", encoding="utf-8")
    assert run_cli(tmp_path, "--places", "2684712", "--config", str(bad)) == 3
    assert "입력 오류" in capsys.readouterr().err
