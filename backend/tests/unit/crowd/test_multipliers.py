"""날짜 배수 M 계산·파일 쓰기(FR-008). 값은 시험용 가짜(TEST FIXTURE)다."""

from datetime import date, datetime
from pathlib import Path

import pytest

from app.modules.crowd import multipliers
from app.modules.crowd.multipliers import day_type_ratios, write_multipliers
from app.modules.crowd.signals import KST, load_inputs

AT = datetime(2026, 11, 26, 6, 0, tzinfo=KST)


def test_past_ratio_by_hand():
    # 2026-11-17(화)~23(월): 평일 17·18·19·20·23, 주말 21·22. 값은 방문자 구분 합.
    values = {(date(2026, 11, day), "영도구"): [60.0, 40.0] for day in (17, 18, 19, 20)}
    values[(date(2026, 11, 23), "영도구")] = [150.0, 50.0]
    values[(date(2026, 11, 21), "영도구")] = [300.0]
    values[(date(2026, 11, 22), "영도구")] = [100.0]
    # 다른 구·군은 따로 평균한다.
    values[(date(2026, 11, 17), "기장군")] = [10.0]

    ratios = day_type_ratios(values, combine="sum")

    # 평일 평균 (100×4 + 200)/5 = 120, 주말 평균 (300+100)/2 = 200
    assert ratios[(date(2026, 11, 23), "영도구")] == pytest.approx(200 / 120)
    assert ratios[(date(2026, 11, 17), "영도구")] == pytest.approx(100 / 120)
    assert ratios[(date(2026, 11, 21), "영도구")] == pytest.approx(1.5)
    assert ratios[(date(2026, 11, 22), "영도구")] == pytest.approx(0.5)
    assert ratios[(date(2026, 11, 17), "기장군")] == pytest.approx(1.0)


def test_future_forecast_uses_mean_of_spots_and_skips_missing_or_zero():
    values = {
        (date(2026, 12, 1), "영도구"): [20.0, 40.0],  # 화, 평균 30
        (date(2026, 12, 2), "영도구"): [10.0],  # 수
        (date(2026, 12, 3), "영도구"): [],  # 관광지 값이 없는 날 → 행 없음
        (date(2026, 12, 4), "영도구"): [0.0],  # 0 → 배수 없음(형식이 0 보다 큰 값만 받는다)
    }
    ratios = day_type_ratios(values, combine="mean")

    # 평일 평균 (30 + 10 + 0)/3
    assert ratios == {
        (date(2026, 12, 1), "영도구"): pytest.approx(30 / (40 / 3)),
        (date(2026, 12, 2), "영도구"): pytest.approx(10 / (40 / 3)),
    }


def test_no_forecast_means_no_rows_and_no_file(tmp_path: Path):
    assert day_type_ratios({}, combine="mean") == {}
    assert write_multipliers(tmp_path, "DATA-07", {}, AT) == 0
    assert not (tmp_path / "crowd_multipliers.csv").exists()


def test_write_merges_sources_and_provider_reads_it(tmp_path: Path):
    write_multipliers(
        tmp_path, "DATA-06", {(date(2026, 11, 20), "영도구"): 0.8, (date(2026, 11, 21), "영도구"): 1.2}, AT
    )
    later = datetime(2026, 11, 27, 6, 0, tzinfo=KST)
    written = write_multipliers(
        tmp_path, "DATA-07", {(date(2026, 11, 21), "영도구"): 1.1, (date(2026, 12, 1), "영도구"): 1.25}, later
    )

    assert written == 2
    inputs = load_inputs(tmp_path)
    got = {key: (item.value, item.source, item.computed_at) for key, item in inputs.multipliers.items()}
    assert got == {
        (date(2026, 11, 20), "영도구"): (0.8, "DATA-06", AT),
        # 같은 (날짜, 구·군) 은 나중 실행 값이 남는다.
        (date(2026, 11, 21), "영도구"): (1.1, "DATA-07", later),
        (date(2026, 12, 1), "영도구"): (1.25, "DATA-07", later),
    }
    assert [p.name for p in tmp_path.iterdir()] == ["crowd_multipliers.csv"]


def test_failed_write_keeps_previous_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_multipliers(tmp_path, "DATA-06", {(date(2026, 11, 20), "영도구"): 0.8}, AT)
    before = (tmp_path / "crowd_multipliers.csv").read_bytes()

    def broken_replace(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(multipliers.os, "replace", broken_replace)
    with pytest.raises(OSError):
        write_multipliers(tmp_path, "DATA-06", {(date(2026, 11, 20), "영도구"): 2.0}, AT)

    assert (tmp_path / "crowd_multipliers.csv").read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["crowd_multipliers.csv"]


def test_unreadable_existing_file_is_not_overwritten(tmp_path: Path):
    path = tmp_path / "crowd_multipliers.csv"
    path.write_text("day,value\n2026-11-20,1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        write_multipliers(tmp_path, "DATA-06", {(date(2026, 11, 20), "영도구"): 2.0}, AT)
    assert path.read_text(encoding="utf-8") == "day,value\n2026-11-20,1\n"

    with pytest.raises(ValueError):
        write_multipliers(tmp_path, "DATA-99", {(date(2026, 11, 20), "영도구"): 2.0}, AT)
