"""FR-008 혼잡도 조회 서비스 단위 테스트."""

from datetime import UTC, date, datetime

from app.modules.crowd.schemas import CrowdHour, PlaceCrowdResponse
from app.modules.crowd.service import CrowdService


class FakeCrowdProvider:
    """테스트용 혼잡도 데이터 제공자."""

    def __init__(self, result=None):
        self.result = result
        self.called_with = None

    def find(self, place_id: str, on_date: date | None):
        self.called_with = (place_id, on_date)
        return self.result


def test_service_returns_provider_data():
    """실제 데이터가 있으면 제공자의 결과를 그대로 반환한다."""
    expected = PlaceCrowdResponse(
        hours=[
            CrowdHour(h=12, grade="보통", score=0.5),
        ],
        confidence="높음",
        as_of=datetime(2026, 11, 26, tzinfo=UTC),
        sources=["test-provider"],
    )
    provider = FakeCrowdProvider(expected)
    service = CrowdService(provider=provider)
    requested_date = date(2026, 11, 24)

    result = service.get("126078", requested_date)

    assert result == expected
    assert provider.called_with == ("126078", requested_date)


def test_service_returns_unknown_when_provider_has_no_data():
    """제공자가 데이터를 찾지 못하면 정보 없음으로 응답한다."""
    provider = FakeCrowdProvider(None)
    service = CrowdService(provider=provider)

    result = service.get("126078")

    assert result.hours == []
    assert result.confidence == "없음"
    assert result.as_of is None
    assert result.sources == []


def test_service_returns_unknown_without_provider():
    """제공자가 연결되지 않아도 임의의 혼잡도를 생성하지 않는다."""
    service = CrowdService()

    result = service.get("126078")

    assert result.hours == []
    assert result.confidence == "없음"
    assert result.as_of is None
    assert result.sources == []
