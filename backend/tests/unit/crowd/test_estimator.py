"""FR-008 예상 혼잡 계산 단위 시험(A3-1·A3-2·A3-3). 입력 값은 모두 시험용 가짜 값이다."""

from datetime import UTC, date, datetime

import pytest

from app.modules.crowd import estimator
from app.modules.crowd.file_provider import FileCrowdProvider
from app.modules.crowd.signals import CrowdConfig, CrowdInputs, Multiplier, SignalLink

WEDNESDAY = date(2026, 11, 25)
SATURDAY = date(2026, 11, 28)
CONFIG = CrowdConfig(grade_percentiles=(0.4, 0.7, 0.9), b_weights={"DATA-04": 1, "DATA-05": 1})


def fake_inputs(*, with_metro: bool = False, with_multiplier: bool = False) -> CrowdInputs:
    """가짜 장소 P1: 평일 10~13시, 주말 10~13시. 값은 손계산이 쉬운 작은 정수."""
    inputs = CrowdInputs()
    inputs.profiles[("DATA-04", "FAKE-DONG")] = {
        "2026-10": {
            ("WEEKDAY", 10): 1,
            ("WEEKDAY", 11): 2,
            ("WEEKDAY", 12): 3,
            ("WEEKDAY", 13): 4,
            ("WEEKEND", 10): 2,
            ("WEEKEND", 11): 4,
            ("WEEKEND", 12): 6,
            ("WEEKEND", 13): 8,
        }
    }
    inputs.links["P1"] = [SignalLink("DATA-04", "FAKE-DONG")]
    if with_metro:
        inputs.profiles[("DATA-05", "FAKE-STN")] = {"2026-05": {("WEEKDAY", h): 5 for h in range(10, 14)}}
        inputs.links["P1"].append(SignalLink("DATA-05", "FAKE-STN"))
    if with_multiplier:
        inputs.multipliers[(WEDNESDAY, "가짜구")] = Multiplier(2.0, "DATA-06", datetime(2026, 11, 24, tzinfo=UTC))
    return inputs


def provider(inputs: CrowdInputs, config: CrowdConfig = CONFIG) -> FileCrowdProvider:
    return FileCrowdProvider(inputs, config, lambda place_id: "가짜구" if place_id == "P1" else None)


@pytest.mark.parametrize(
    ("count", "expected"),
    [(0, "없음"), (1, "낮음"), (2, "중간"), (3, "높음"), (4, "높음")],
)
def test_confidence_by_signal_count(count, expected):
    assert estimator.confidence(count) == expected


def test_signal_count_drives_confidence_and_zero_signals_is_unknown():
    # 신호 0개: 연결 없는 장소 → None(서비스가 정보 부족, hours 비움)
    assert provider(fake_inputs()).find("OTHER", WEDNESDAY) is None
    assert provider(fake_inputs()).find("P1", WEDNESDAY).confidence == "낮음"
    assert provider(fake_inputs(with_metro=True)).find("P1", WEDNESDAY).confidence == "중간"
    full = provider(fake_inputs(with_metro=True, with_multiplier=True)).find("P1", WEDNESDAY)
    assert full.confidence == "높음"
    assert [signal.source for signal in full.signals] == ["DATA-04", "DATA-05", "DATA-06"]


def test_multiplier_file_adds_one_signal_and_changes_as_of():
    without = provider(fake_inputs()).find("P1", WEDNESDAY)
    with_m = provider(fake_inputs(with_multiplier=True)).find("P1", WEDNESDAY)
    assert (without.confidence, with_m.confidence) == ("낮음", "중간")
    assert len(with_m.signals) == len(without.signals) + 1
    assert without.as_of == datetime.fromisoformat("2026-10-01T00:00:00+09:00")
    assert with_m.as_of == datetime(2026, 11, 24, tzinfo=UTC)
    # M 이 방문일에 없으면(토요일) 세지 않는다.
    assert provider(fake_inputs(with_multiplier=True)).find("P1", SATURDAY).confidence == "낮음"


def test_without_multiplier_there_is_no_multiplication():
    base = 1.2345
    # 곱셈이 없으므로 같은 객체 그대로 돌아온다(상수 M=1 을 곱하지 않음).
    assert estimator.score(base, None) is base
    assert estimator.score(base, 2.0) == pytest.approx(2.469)


def test_relative_and_base_profile_hand_calculation():
    relative = estimator.relative({("WEEKDAY", 10): 1, ("WEEKDAY", 11): 3})
    assert relative == {("WEEKDAY", 10): 0.5, ("WEEKDAY", 11): 1.5}
    assert estimator.relative({("WEEKDAY", 10): 0}) is None
    assert estimator.relative({}) is None
    base = estimator.base_profile([(1, {("WEEKDAY", 10): 0.5, ("WEEKDAY", 11): 1.5}), (3, {("WEEKDAY", 10): 1.5})])
    # 10시: (1×0.5 + 3×1.5) / 4 = 1.25, 11시: 첫 신호만 → 1.5
    assert base == {("WEEKDAY", 10): 1.25, ("WEEKDAY", 11): 1.5}


def test_percentile_uses_mid_rank():
    assert estimator.percentile(3, [1, 2, 3, 4]) == pytest.approx(0.625)
    assert estimator.percentile(5, [5, 5, 5]) == 0.5
    with pytest.raises(ValueError):
        estimator.percentile(1, [])


def test_grade_follows_configured_cutoffs():
    assert [estimator.grade(rank, (0.4, 0.7, 0.9)) for rank in (0.1, 0.4, 0.69, 0.7, 0.9, 1.0)] == [
        "여유",
        "보통",
        "보통",
        "붐빔",
        "매우 붐빔",
        "매우 붐빔",
    ]
    assert estimator.grade(0.5, (0.6, 0.8, 0.95)) == "여유"


def test_changing_config_cutoffs_changes_grades():
    # 백분위(0.0625, 0.25, 0.4375, 0.625)는 그대로이고 경계만 바뀐다.
    default = provider(fake_inputs()).find("P1", WEDNESDAY)
    strict = provider(fake_inputs(), CrowdConfig(grade_percentiles=(0.05, 0.1, 0.15), b_weights={"DATA-04": 1})).find(
        "P1", WEDNESDAY
    )
    assert [hour.score for hour in default.hours] == [hour.score for hour in strict.hours]
    assert [hour.grade for hour in default.hours] == ["여유", "여유", "보통", "보통"]
    assert [hour.grade for hour in strict.hours] == ["보통", "매우 붐빔", "매우 붐빔", "매우 붐빔"]


def test_hand_calculated_scores_without_multiplier():
    # 평균 = (1+2+3+4+2+4+6+8)/8 = 3.75 → 상대값은 원래 값 순서와 같다.
    # 분포(원값 기준) [1,2,3,4,2,4,6,8]. 평일 10시(1): (0 + 0.5)/8 = 0.0625, 11시(2): (1 + 1)/8 = 0.25,
    # 12시(3): (3 + 0.5)/8 = 0.4375, 13시(4): (4 + 1)/8 = 0.625
    result = provider(fake_inputs()).find("P1", WEDNESDAY)
    assert [(hour.h, hour.score, hour.grade) for hour in result.hours] == [
        (10, 0.0625, "여유"),
        (11, 0.25, "여유"),
        (12, 0.4375, "보통"),
        (13, 0.625, "보통"),
    ]


def test_hand_calculated_scores_with_multiplier_distribution():
    # M 은 가짜구 수요일 2.0 하나뿐 → 분포는 평일 B × 2.0 4개. 순위는 B 와 같다: (0.5, 1.5, 2.5, 3.5)/4
    result = provider(fake_inputs(with_multiplier=True)).find("P1", WEDNESDAY)
    assert [hour.score for hour in result.hours] == [0.125, 0.375, 0.625, 0.875]
    assert [hour.grade for hour in result.hours] == ["여유", "여유", "보통", "붐빔"]


def test_weight_missing_from_config_excludes_signal():
    config = CrowdConfig(grade_percentiles=(0.4, 0.7, 0.9), b_weights={"DATA-05": 1})
    assert provider(fake_inputs(), config).find("P1", WEDNESDAY) is None


def test_day_type_without_hours_is_unknown():
    inputs = CrowdInputs()
    inputs.profiles[("DATA-04", "FAKE-DONG")] = {"2026-10": {("WEEKDAY", 10): 1}}
    inputs.links["P1"] = [SignalLink("DATA-04", "FAKE-DONG")]
    assert provider(inputs).find("P1", SATURDAY) is None


def test_invalid_config_is_rejected():
    with pytest.raises(ValueError):
        CrowdConfig(grade_percentiles=(0.7, 0.4, 0.9), b_weights={"DATA-04": 1})
    with pytest.raises(ValueError):
        CrowdConfig(grade_percentiles=(0.4, 0.7, 0.9), b_weights={"DATA-04": 0})
