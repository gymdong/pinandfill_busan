"""경로 공급자 선택. 네트워크를 쓰지 않는다(전송 계층을 가짜로 바꿔 호출 여부만 본다)."""

from datetime import UTC, datetime

import pytest

from app.adapters.route import service as route_service
from app.adapters.route.service import LiveRouteProvider, UnconfiguredRouteProvider, build_route_provider
from app.adapters.route.settings import ODsaySettings, TMAPSettings
from app.adapters.route.transport import HttpReply
from app.modules.engine.schemas import PublicPlaceRef, TransientPlaceDetails

ORIGIN = TransientPlaceDetails(place_ref=PublicPlaceRef(place_id="a"), lat=35.10, lng=129.10)
DESTINATION = TransientPlaceDetails(place_ref=PublicPlaceRef(place_id="b"), lat=35.20, lng=129.20)
DEPARTURE = datetime(2026, 11, 20, 10, tzinfo=UTC)


def settings(tmap: str | None = None, odsay: str | None = None) -> tuple[TMAPSettings, ODsaySettings]:
    return TMAPSettings(_env_file=None, api_key=tmap), ODsaySettings(_env_file=None, api_key=odsay)


class RecordingTransport:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def post(self, url, *, headers, body, encoding, timeout) -> HttpReply:
        self.urls.append(url)
        return HttpReply(500, {})


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> RecordingTransport:
    recording = RecordingTransport()
    monkeypatch.setattr(route_service, "SafeHTTPTransport", lambda: recording)
    return recording


@pytest.mark.parametrize("keys", [(None, None), ("", ""), ("   ", "\t\n")])
def test_without_keys_routes_are_not_looked_up(keys, transport):
    provider = build_route_provider(*settings(*keys))
    assert isinstance(provider, UnconfiguredRouteProvider)
    estimate = provider.estimate(ORIGIN, DESTINATION, mode="TRANSIT")
    # 이동시간을 지어내지 않는다. 엔진은 이 구간을 '이동시간 확인 필요'로 둔다.
    assert (estimate.duration_min, estimate.source) == (None, "UNKNOWN")
    assert transport.urls == []


def test_settings_read_the_documented_environment_names(monkeypatch):
    monkeypatch.setenv("TMAP_API_KEY", "test-tmap")
    monkeypatch.setenv("ODSAY_API_KEY", "test-odsay")
    tmap, odsay = TMAPSettings(_env_file=None), ODsaySettings(_env_file=None)
    assert tmap.api_key is not None and tmap.api_key.get_secret_value() == "test-tmap"
    assert odsay.api_key is not None and odsay.api_key.get_secret_value() == "test-odsay"
    assert "test-tmap" not in repr(tmap)


def test_tmap_key_uses_tmap_without_fallback(transport):
    provider = build_route_provider(*settings(tmap="test-tmap"))
    assert isinstance(provider, LiveRouteProvider) and provider.fallback is None
    assert provider.estimate_at(ORIGIN, DESTINATION, mode="TRANSIT", departure_at=DEPARTURE).duration_min is None
    assert transport.urls == ["https://apis.openapi.sk.com/transit/routes"]


def test_both_keys_fall_back_to_odsay(transport):
    provider = build_route_provider(*settings(tmap="test-tmap", odsay="test-odsay"))
    assert isinstance(provider, LiveRouteProvider) and provider.fallback is not None
    provider.estimate_at(ORIGIN, DESTINATION, mode="TRANSIT", departure_at=DEPARTURE)
    assert transport.urls == ["https://apis.openapi.sk.com/transit/routes", "https://api.odsay.com/v1/api/maasRP"]


def test_odsay_key_alone_skips_tmap_calls(transport):
    provider = build_route_provider(*settings(odsay="test-odsay"))
    assert isinstance(provider, LiveRouteProvider)
    estimate = provider.estimate_at(ORIGIN, DESTINATION, mode="TRANSIT", departure_at=DEPARTURE)
    assert estimate.source == "UNKNOWN"
    assert transport.urls == ["https://api.odsay.com/v1/api/maasRP"]
