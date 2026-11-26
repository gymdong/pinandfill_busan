"""FR-009 엔진용 혼잡 조회 어댑터 시험."""

from datetime import UTC, date, datetime

from app.modules.crowd.engine_lookup import CrowdServiceLookup
from app.modules.crowd.schemas import CrowdHour, PlaceCrowdResponse
from app.modules.crowd.service import CrowdService
from app.modules.engine.schemas import KakaoPlaceRef, PublicPlaceRef

CROWD = PlaceCrowdResponse(
    hours=[CrowdHour(h=10, score=0.5)],
    confidence="높음",
    as_of=datetime(2026, 11, 26, tzinfo=UTC),
    sources=["test-provider"],
)


class Provider:
    def __init__(self):
        self.calls = []

    def find(self, place_id, on_date):
        self.calls.append((place_id, on_date))
        return CROWD


def test_public_place_is_looked_up_with_its_date():
    provider = Provider()
    lookup = CrowdServiceLookup(CrowdService(provider))
    assert lookup.crowd(PublicPlaceRef(place_id="126658"), on_date=date(2026, 11, 28)) == CROWD
    assert provider.calls == [("126658", date(2026, 11, 28))]


def test_kakao_place_has_no_crowd_and_is_not_looked_up():
    provider = Provider()
    lookup = CrowdServiceLookup(CrowdService(provider))
    ref = KakaoPlaceRef(kakao_place_id="900000009", placeUrl="https://place.map.kakao.com/900000009")
    assert lookup.crowd(ref, on_date=date(2026, 11, 28)) is None
    assert provider.calls == []


def test_empty_service_returns_no_information():
    result = CrowdServiceLookup(CrowdService()).crowd(PublicPlaceRef(place_id="1"), on_date=date(2026, 11, 28))
    assert result is not None and result.confidence == "없음"
