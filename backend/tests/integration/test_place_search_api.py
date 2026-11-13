"""API-003 장소 검색 통합 테스트. 카카오는 가짜 공급자로 대신하며 장소 값은 모두 직접 만든 예시다."""

import logging
from datetime import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.kakao import KakaoLocalAdapter, KakaoLocalError, KakaoPlace, KakaoSettings
from app.core.config import Settings
from app.main import create_app
from app.modules.places import PlaceHours, PlaceMatcher, PlaceMatchSettings, PlaceSearchService, PublicPlace
from app.modules.places.repository import InMemoryPublicPlaceRepository

SETTINGS = PlaceMatchSettings(match_radius_m=100.0, name_similarity_threshold=0.8, search_query_max_length=50)
OPEN = PlaceHours(day_type="MON", open_time=time(9), close_time=time(18))
PUBLIC_PLACES = [
    PublicPlace(id="public-park", name="예시해변공원", lat=35.15, lng=129.12, category="공원", hours=(OPEN,)),
    PublicPlace(id="public-market", name="예시회센터", lat=35.151, lng=129.121, category="시장"),
]


def kakao_place(kakao_place_id: str, name: str, lat: float, lng: float, **extra: str) -> KakaoPlace:
    return KakaoPlace(
        kakao_place_id=kakao_place_id,
        name=name,
        lat=lat,
        lng=lng,
        place_url=f"http://place.map.kakao.com/{kakao_place_id}",
        **extra,
    )


KAKAO_RESULTS = [
    kakao_place("900000001", "예시 해변공원", 35.15, 129.12, category_name="여행 > 공원", road_address="부산 예시로 1"),
    kakao_place("900000002", "예시회센터", 35.151, 129.121, category_name="음식점 > 시장", address="부산 예시동 2"),
    kakao_place("900000003", "예시카페", 35.152, 129.122, category_name="음식점 > 카페"),
]


class FakeKakao:
    def __init__(self, places: list[KakaoPlace] | None = None, error: KakaoLocalError | None = None) -> None:
        self.places = KAKAO_RESULTS if places is None else places
        self.error = error
        self.calls: list[tuple[str, str | None]] = []

    async def search_keyword(self, query: str, *, category_group_code: str | None = None) -> list[KakaoPlace]:
        self.calls.append((query, category_group_code))
        if self.error:
            raise self.error
        return self.places


def make_client(kakao, repository=None) -> TestClient:
    matcher = PlaceMatcher(repository or InMemoryPublicPlaceRepository(PUBLIC_PLACES), SETTINGS)
    service = PlaceSearchService(kakao, matcher, SETTINGS)
    return TestClient(create_app(Settings(app_name="Backend test"), place_search_service=service))


def test_search_returns_places_with_match_and_badges():
    kakao = FakeKakao()
    with make_client(kakao) as client:
        response = client.get("/api/places/search", params={"q": "  예시  "})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert kakao.calls == [("예시", None)]
    park, market, cafe = response.json()["places"]
    assert park == {
        "placeId": "public-park",
        "kakaoPlaceId": "900000001",
        "placeUrl": "https://place.map.kakao.com/900000001",
        "name": "예시 해변공원",
        "coords": {"lat": 35.15, "lng": 129.12},
        "category": "공원",
        "address": "부산 예시로 1",
        "badge": "DETAIL",
        "hoursStatus": "KNOWN",
    }
    # 공공 DB 와 매칭됐지만 영업시간이 없으면 '확인 필요'
    assert (market["placeId"], market["badge"], market["hoursStatus"]) == ("public-market", "DETAIL", "NEEDS_CHECK")
    assert market["address"] == "부산 예시동 2"
    # 매칭되지 않은 장소도 결과에 남는다(AC-001)
    assert (cafe["placeId"], cafe["badge"], cafe["hoursStatus"]) == (None, "BASIC", "NEEDS_CHECK")
    assert (cafe["category"], cafe["address"]) == ("카페", None)


def test_successful_search_logs_no_query_or_place_data(caplog):
    with caplog.at_level(logging.DEBUG), make_client(FakeKakao()) as client:
        client.get("/api/places/search", params={"q": "비밀검색어"})

    for leaked in ("비밀검색어", "예시 해변공원", "부산 예시로 1", "129.12"):
        assert leaked not in caplog.text


def test_no_results():
    with make_client(FakeKakao(places=[])) as client:
        response = client.get("/api/places/search", params={"q": "없는곳"})

    assert response.status_code == 200
    assert response.json() == {"places": []}


def test_category_is_passed_to_kakao():
    kakao = FakeKakao()
    with make_client(kakao) as client:
        client.get("/api/places/search", params={"q": "예시", "category": "CE7"})

    assert kakao.calls == [("예시", "CE7")]


@pytest.mark.parametrize(
    "params",
    [{}, {"q": ""}, {"q": "   "}, {"q": "가" * 51}, {"q": "예시", "category": "카페"}, {"q": "예시", "category": ""}],
)
def test_invalid_request_is_rejected_without_calling_kakao(params):
    kakao = FakeKakao()
    with make_client(kakao) as client:
        response = client.get("/api/places/search", params=params)

    assert response.status_code == 400
    assert response.json()["error"]["id"] == "ERR-001"
    assert response.headers["cache-control"] == "no-store"
    assert kakao.calls == []


def test_query_at_max_length_is_accepted():
    with make_client(FakeKakao()) as client:
        assert client.get("/api/places/search", params={"q": "가" * 50}).status_code == 200


@pytest.mark.parametrize("reason", ["timeout", "network", "quota_exceeded", "auth", "http_status", "invalid_response"])
def test_kakao_failure_is_err_003_without_leaking_query(reason, caplog):
    secret = "비밀검색어"
    with caplog.at_level(logging.DEBUG), make_client(FakeKakao(error=KakaoLocalError(reason, 500))) as client:
        response = client.get("/api/places/search", params={"q": secret})

    assert response.status_code == 503
    assert response.json()["error"]["id"] == "ERR-003"
    assert response.headers["cache-control"] == "no-store"
    assert secret not in response.text
    assert secret not in caplog.text


def test_unconfigured_service_is_err_017(client: TestClient):
    response = client.get("/api/places/search", params={"q": "예시"})

    assert response.status_code == 503
    assert response.json()["error"]["id"] == "ERR-017"
    assert response.headers["cache-control"] == "no-store"


def test_public_db_failure_is_err_017_without_leaking_kakao_data(caplog):
    class BrokenRepository(InMemoryPublicPlaceRepository):
        def find_near(self, lat, lng, radius_m):
            raise RuntimeError(f"db down [parameters: ({lat}, {lng})]")

    with caplog.at_level(logging.DEBUG), make_client(FakeKakao(), BrokenRepository([])) as client:
        response = client.get("/api/places/search", params={"q": "비밀검색어"})

    assert response.status_code == 503
    assert response.json()["error"]["id"] == "ERR-017"
    assert response.headers["cache-control"] == "no-store"
    assert "place_lookup failed error=RuntimeError count=3" in caplog.text
    for leaked in ("35.15", "129.12", "예시 해변공원", "비밀검색어", "db down"):
        assert leaked not in response.text
        assert leaked not in caplog.text


def test_real_adapter_end_to_end_keeps_query_and_place_data_out_of_logs(respx_mock, caplog, monkeypatch):
    """실제 어댑터와 httpx 를 거쳐도(카카오만 가짜) 검색어와 장소 정보가 로그에 남지 않는다."""
    document = {
        "id": "900000001",
        "place_name": "예시 해변공원",
        "category_name": "여행 > 공원",
        "address_name": "부산 수영구 예시동 1-1",
        "road_address_name": "부산 수영구 예시해변로 1",
        "x": "129.12",
        "y": "35.15",
        "place_url": "http://place.map.kakao.com/900000001",
    }
    respx_mock.get("https://dapi.kakao.com/v2/local/search/keyword.json").respond(json={"documents": [document]})
    monkeypatch.setattr(logging.getLogger("httpx"), "level", logging.DEBUG)

    async def run() -> httpx.Response:
        async with httpx.AsyncClient() as kakao_http:
            adapter = KakaoLocalAdapter(kakao_http, KakaoSettings(rest_api_key="test-rest-key", _env_file=None))
            matcher = PlaceMatcher(InMemoryPublicPlaceRepository(PUBLIC_PLACES), SETTINGS)
            application = create_app(Settings(), place_search_service=PlaceSearchService(adapter, matcher, SETTINGS))
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
                return await api.get("/api/places/search", params={"q": "비밀검색어"})

    with caplog.at_level(logging.DEBUG):
        import anyio

        response = anyio.run(run)

    assert response.status_code == 200
    assert response.json()["places"][0]["placeId"] == "public-park"
    assert "kakao_local_search status=200" in caplog.text
    for leaked in (
        "비밀검색어",
        "%EB%B9%84%EB%B0%80",
        "예시 해변공원",
        "예시해변로",
        "129.12",
        "35.15",
        "test-rest-key",
    ):
        assert leaked not in caplog.text


def test_openapi_lists_search_endpoint(client: TestClient):
    assert "/api/places/search" in client.get("/openapi.json").json()["paths"]
