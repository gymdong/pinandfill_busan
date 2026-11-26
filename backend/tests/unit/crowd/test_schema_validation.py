"""FR-008 혼잡도 응답 일관성 검증 테스트."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.modules.crowd.schemas import CrowdHour, CrowdSignal, PlaceCrowdResponse


def sample_hour():
    return CrowdHour(h=12, grade="보통", score=0.5)


def test_hours_require_as_of():
    with pytest.raises(ValidationError):
        PlaceCrowdResponse(
            hours=[sample_hour()],
            confidence="높음",
            sources=["test-provider"],
        )


def test_hours_require_sources():
    with pytest.raises(ValidationError):
        PlaceCrowdResponse(
            hours=[sample_hour()],
            confidence="높음",
            as_of=datetime(2026, 11, 26, tzinfo=UTC),
            sources=[],
        )


def test_unknown_confidence_rejects_hours():
    with pytest.raises(ValidationError):
        PlaceCrowdResponse(
            hours=[sample_hour()],
            confidence="없음",
            as_of=datetime(2026, 11, 26, tzinfo=UTC),
            sources=["test-provider"],
        )


def test_valid_crowd_response():
    response = PlaceCrowdResponse(
        hours=[sample_hour()],
        confidence="높음",
        as_of=datetime(2026, 11, 26, tzinfo=UTC),
        sources=["test-provider"],
    )
    assert len(response.hours) == 1


def test_duplicate_hour_is_rejected():
    with pytest.raises(ValidationError):
        PlaceCrowdResponse(
            hours=[sample_hour(), CrowdHour(h=12, grade="붐빔", score=0.8)],
            confidence="높음",
            as_of=datetime(2026, 11, 26, tzinfo=UTC),
            sources=["test-provider"],
        )


def test_signals_serialize_in_camel_case_and_default_empty():
    assert PlaceCrowdResponse().model_dump(by_alias=True, mode="json")["signals"] == []
    response = PlaceCrowdResponse(
        hours=[sample_hour()],
        confidence="낮음",
        as_of=datetime(2026, 11, 26, tzinfo=UTC),
        sources=["test-provider"],
        signals=[CrowdSignal(source="DATA-04", label="test-signal", ref_period="2026-10")],
    )
    assert response.model_dump(by_alias=True, mode="json")["signals"] == [
        {"source": "DATA-04", "label": "test-signal", "refPeriod": "2026-10", "detail": None}
    ]


def test_signal_requires_source_and_label():
    with pytest.raises(ValidationError):
        CrowdSignal(source="", label="x")
