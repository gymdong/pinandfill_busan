"""FR-009 혼잡 회피 추천 테스트."""

from datetime import UTC, datetime

import pytest

from app.modules.crowd.avoidance import suggest_less_crowded_hour
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
