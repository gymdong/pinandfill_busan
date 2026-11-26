"""FR-009 혼잡 회피 추천 테스트."""

from datetime import UTC, datetime, time

import pytest

from app.modules.crowd.avoidance import (
    AvoidanceSettings,
    meets_confidence,
    pick_less_crowded,
    suggest_less_crowded_hour,
    window_cost,
)
from app.modules.crowd.schemas import CrowdHour, PlaceCrowdResponse


def sample_crowd():
    return PlaceCrowdResponse(
        hours=[
            CrowdHour(h=10, grade="붐빔", score=0.8),
            CrowdHour(h=11, grade="보통", score=0.5),
            CrowdHour(h=12, grade="여유", score=0.2),
        ],
        confidence="높음",
        as_of=datetime(2026, 11, 26, tzinfo=UTC),
        sources=["test-provider"],
    )


def test_recommends_less_crowded_hour():
    assert suggest_less_crowded_hour(sample_crowd(), 10) == 12


def test_fixed_schedule_is_not_changed():
    assert suggest_less_crowded_hour(sample_crowd(), 10, is_fixed=True) is None


def test_no_better_hour():
    assert suggest_less_crowded_hour(sample_crowd(), 12) is None


def test_unknown_crowd_returns_none():
    crowd = PlaceCrowdResponse()
    assert suggest_less_crowded_hour(crowd, 10) is None


def test_missing_current_hour_returns_none():
    assert suggest_less_crowded_hour(sample_crowd(), 15) is None


def test_invalid_hour():
    with pytest.raises(ValueError):
        suggest_less_crowded_hour(sample_crowd(), 24)


def test_recommends_only_allowed_hour():
    assert (
        suggest_less_crowded_hour(
            sample_crowd(),
            10,
            allowed_hours={10, 11},
        )
        == 11
    )


def test_no_allowed_alternative():
    assert (
        suggest_less_crowded_hour(
            sample_crowd(),
            10,
            allowed_hours={10},
        )
        is None
    )


def test_empty_allowed_hours():
    assert (
        suggest_less_crowded_hour(
            sample_crowd(),
            10,
            allowed_hours=set(),
        )
        is None
    )


def crowd_of(scores, confidence="높음"):
    return PlaceCrowdResponse(
        hours=[CrowdHour(h=h, score=score) for h, score in scores.items()],
        confidence=confidence,
        as_of=datetime(2026, 11, 26, tzinfo=UTC),
        sources=["test-provider"],
    )


def test_equal_distance_tie_prefers_earlier_hour():
    crowd = crowd_of({10: 0.2, 12: 0.8, 14: 0.2})
    assert suggest_less_crowded_hour(crowd, 12) == 10


def test_score_none_hours_are_skipped_by_hour_suggestion():
    crowd = crowd_of({10: 0.8, 11: None, 12: 0.5})
    assert suggest_less_crowded_hour(crowd, 10) == 12
    assert suggest_less_crowded_hour(crowd, 11) is None


# FR-009 삽입 위치 선택(#57 리뷰 후속): 체류 구간 평균, 신뢰도 기준, 최소 이득


def test_window_cost_averages_every_hour_the_stay_touches():
    crowd = crowd_of({10: 0.8, 11: 0.4, 12: 0.1})
    assert window_cost(crowd, time(10), time(11)) == pytest.approx(0.8)  # 끝 시각 11:00 은 포함하지 않는다
    assert window_cost(crowd, time(10, 30), time(11, 15)) == pytest.approx(0.6)
    assert window_cost(crowd, time(10), time(12, 1)) == pytest.approx((0.8 + 0.4 + 0.1) / 3)


def test_window_cost_skips_hours_without_score():
    crowd = crowd_of({10: 0.8, 11: None, 12: 0.2})
    assert window_cost(crowd, time(10), time(13)) == pytest.approx(0.5)
    assert window_cost(crowd, time(11), time(12)) is None
    assert window_cost(crowd, time(15), time(16)) is None


def test_pick_less_crowded_chooses_lowest_window_with_enough_gain():
    crowd = crowd_of({10: 0.9, 11: 0.9, 13: 0.5, 14: 0.2})
    windows = [(time(10), time(12)), (time(13), time(14)), (time(14), time(15))]
    assert pick_less_crowded(crowd, windows, min_gain=0.1) == 2


def test_pick_less_crowded_needs_min_gain():
    crowd = crowd_of({10: 0.5, 14: 0.45})
    windows = [(time(10), time(11)), (time(14), time(15))]
    assert pick_less_crowded(crowd, windows, min_gain=0.1) is None
    assert pick_less_crowded(crowd, windows, min_gain=0.05) == 1


def test_pick_less_crowded_tie_keeps_earlier_candidate():
    crowd = crowd_of({10: 0.9, 13: 0.2, 15: 0.2})
    windows = [(time(10), time(11)), (time(13), time(14)), (time(15), time(16))]
    assert pick_less_crowded(crowd, windows, min_gain=0.1) == 1


def test_low_confidence_never_moves_a_block_by_default():
    windows = [(time(10), time(11)), (time(14), time(15))]
    low = crowd_of({10: 0.9, 14: 0.1}, "낮음")
    assert pick_less_crowded(low, windows, min_gain=0.1) is None
    assert pick_less_crowded(PlaceCrowdResponse(), windows, min_gain=0.1) is None
    assert not meets_confidence(low, "중간")
    assert meets_confidence(crowd_of({10: 0.9}, "중간"), "중간")
    # 기준을 설정으로 낮췄을 때만 '낮음' 정보로 옮긴다
    assert pick_less_crowded(low, windows, min_gain=0.1, min_confidence="낮음") == 1


def test_pick_less_crowded_skips_unknown_windows():
    crowd = crowd_of({10: 0.9, 13: None, 15: 0.5})
    windows = [(time(10), time(11)), (time(13), time(14)), (time(15), time(16))]
    assert pick_less_crowded(crowd, windows, min_gain=0.1) == 2
    # 첫 후보의 비용을 모르면 비교 근거가 없으므로 지금 동작(첫 후보)
    assert pick_less_crowded(crowd, [(time(13), time(14)), (time(15), time(16))], min_gain=0.1) is None


def test_pick_less_crowded_without_data_or_candidates():
    assert pick_less_crowded(None, [(time(10), time(11))], min_gain=0.1) is None
    assert pick_less_crowded(crowd_of({10: 0.9}), [], min_gain=0.1) is None


def test_avoidance_defaults_follow_spec():
    settings = AvoidanceSettings()
    assert (settings.min_confidence, settings.min_gain) == ("중간", 0.1)
