"""FR-008 혼잡 입력 파일·설정 로더 시험. tests/fixtures/crowd 는 시험용 가짜 값이다."""

import json
import logging
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.crowd.file_provider import CROWD_CONFIG, district
from app.modules.crowd.signals import SignalLink, load_config, load_inputs

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "crowd"


def test_missing_directory_gives_empty_inputs(tmp_path):
    inputs = load_inputs(tmp_path / "nothing")
    assert inputs.profiles == {} and inputs.multipliers == {} and inputs.links == {}


def test_fixture_files_load_and_broken_rows_are_skipped(caplog):
    with caplog.at_level(logging.WARNING):
        inputs = load_inputs(FIXTURES)
    living = inputs.profiles[("DATA-04", "TEST-DONG-1")]
    assert set(living) == {"2026-09", "2026-10"}
    # 9~17시 × 평일·주말 = 18칸. 깨진 행(HOLIDAY, 24시)은 들어가지 않는다.
    assert len(living["2026-10"]) == 18
    metro = inputs.profiles[("DATA-05", "TEST-STN-1")]["2026-05"]
    assert metro[("WEEKDAY", 9)] == 30  # 승차 20 + 하차 10
    assert inputs.station_names["TEST-STN-1"] == "시험역"
    assert (date(2026, 11, 29), "영도구") not in inputs.multipliers  # 음수 배수
    assert inputs.multipliers[(date(2026, 11, 28), "영도구")].value == 1.5
    assert inputs.links["126078"] == [SignalLink("DATA-04", "TEST-DONG-2")]  # 모르는 신호는 건너뜀
    assert "skipped_rows file=living_population.csv count=2" in caplog.text


def test_comment_lines_and_duplicates(tmp_path):
    (tmp_path / "living_population.csv").write_text(
        "# 시험용 가짜 값\nref_month,adm_dong_code,day_type,hour,population\n"
        "2026-10,D,WEEKDAY,9,10\n2026-10,D,WEEKDAY,9,99\n",
        encoding="utf-8",
    )
    inputs = load_inputs(tmp_path)
    assert inputs.profiles[("DATA-04", "D")]["2026-10"] == {("WEEKDAY", 9): 10}


def test_multiplier_source_must_be_data06_or_data07(tmp_path, caplog):
    (tmp_path / "crowd_multipliers.csv").write_text(
        "date,region,multiplier,source,computed_at\n"
        "2026-11-28,영도구,1.2,DATA-07,2026-11-24T06:00:00\n"
        "2026-11-29,영도구,1.2,MANUAL,2026-11-24T06:00:00\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING):
        inputs = load_inputs(tmp_path)
    assert list(inputs.multipliers) == [(date(2026, 11, 28), "영도구")]
    assert "skipped_rows file=crowd_multipliers.csv count=1" in caplog.text


def test_unreadable_file_is_empty(tmp_path):
    (tmp_path / "metro_hourly.csv").write_bytes(b"\xff\xfe\x00bad")
    assert load_inputs(tmp_path).profiles == {}


def test_repo_config_file_values():
    config = load_config(CROWD_CONFIG)
    assert config.grade_percentiles == (0.4, 0.7, 0.9)
    assert config.b_weights == {"DATA-04": 1, "DATA-05": 1}
    assert (config.avoidance.min_confidence, config.avoidance.min_gain) == ("중간", 0.1)


def test_avoidance_config_values_are_used_and_validated(tmp_path):
    path = tmp_path / "crowd_config.json"
    base = {"grade_percentiles": [0.4, 0.7, 0.9], "b_weights": {"DATA-04": 1}}
    path.write_text(json.dumps(base), encoding="utf-8")
    assert load_config(path).avoidance.min_confidence == "중간"  # 칸이 없으면 기본값
    path.write_text(json.dumps({**base, "avoidance": {"min_confidence": "높음", "min_gain": 0.2}}), encoding="utf-8")
    assert (load_config(path).avoidance.min_confidence, load_config(path).avoidance.min_gain) == ("높음", 0.2)
    path.write_text(json.dumps({**base, "avoidance": {"min_confidence": "매우"}}), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(path)


def test_config_file_values_are_used(tmp_path):
    path = tmp_path / "crowd_config.json"
    path.write_text(json.dumps({"grade_percentiles": [0.2, 0.5, 0.8], "b_weights": {"DATA-05": 2}}), encoding="utf-8")
    config = load_config(path)
    assert config.grade_percentiles == (0.2, 0.5, 0.8)
    assert config.b_weights == {"DATA-05": 2}
    path.write_text(json.dumps({"grade_percentiles": [0.2, 0.5], "b_weights": {"DATA-05": 2}}), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(path)


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("부산광역시 영도구 전망로 24", "영도구"),
        ("부산광역시 기장군 기장읍 용궁길 86", "기장군"),
        ("영도구 절영로 194", "영도구"),
        ("부산 중구 용두산길 37-55", "중구"),
        ("주소 미상", None),
        (None, None),
    ],
)
def test_district(address, expected):
    assert district(address) == expected
