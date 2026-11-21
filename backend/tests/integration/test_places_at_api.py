"""API-004 지도 길게 누르기 통합 테스트. 카카오는 가짜 공급자로 대신하며 장소 값은 모두 직접 만든 예시다."""

import logging

import pytest
from fastapi.testclient import TestClient

from app.adapters.kakao import KakaoLocalError, KakaoPlace
from app.core.config import Settings
from app.main import create_app
from app.modules.places import PlaceMatcher, PlaceMatchSettings, PlaceSearchService, PublicPlace
from app.modules.places.repository import InMemoryPublicPlaceRepository

SETTINGS = PlaceMatchSettings(
    match_radius_m=100.0,
    name_similarity_threshold=0.8,
    search_query_max_length=50,
    nearby_radius_m=100,
    nearby_category_codes=("AT4", "CE7"),
    nearby_max_results=2,
)
PRESS = {"lat": 35.15, "lng": 129.12}
PUBLIC = [PublicPlace(id="public-park", name="예시해변공원", lat=35.1501, lng=129.1201, category="공원")]


def kakao_place(kakao_place_id: str, name: str, lat: float, lng: float) -> KakaoPlace:
    return KakaoPlace(
        kakao_place_id=kakao_place_id,
        name=name,
        lat=lat,
        lng=lng,
        place_url=f"http://place.map.kakao.com/{kakao_place_id}",
        address="부산 예시동 1",
    )


PARK = kakao_place("900000001", "예시 해변공원", 35.1501, 129.1201)  # 약 14m
CAFE = kakao_place("900000002", "예시카페", 35.1505, 129.1205)  # 약 71m
# 약 107m. 반경은 카카오가 거르고 서비스는 다시 거르지 않는다. 가짜 공급자는 거르지 않으니 정렬·상한만 확인한다.
FAR_CAFE = kakao_place("900000003", "먼 카페", 35.1508, 129.1207)


class FakeKakao:
    def __init__(self, by_code: dict[str, list[KakaoPlace]] | None = None, fail_code: str | None = None) -> None:
        # 공원은 관광명소·카페 두 분류에 모두 나온다(중복 제거 확인).
        self.by_code = by_code if by_code is not None else {"AT4": [PARK], "CE7": [FAR_CAFE, CAFE, PARK]}
        self.fail_code = fail_code
        self.calls: list[tuple[str, float, float, int]] = []

    async def search_keyword(self, query: str, *, category_group_code: str | None = None) -> list[KakaoPlace]:
        raise AssertionError("API-004 는 키워드 검색을 쓰지 않는다")

    async def search_category(
        self, category_group_code: str, *, lat: float, lng: float, radius_m: int
    ) -> list[KakaoPlace]:
        self.calls.append((category_group_code, lat, lng, radius_m))
        if category_group_code == self.fail_code:
            raise KakaoLocalError("quota_exceeded", 400)
        return self.by_code.get(category_group_code, [])


def make_client(kakao: FakeKakao) -> TestClient:
    service = PlaceSearchService(kakao, PlaceMatcher(InMemoryPublicPlaceRepository(PUBLIC), SETTINGS), SETTINGS)
    return TestClient(create_app(Settings(app_name="Backend test"), place_search_service=service))


def test_merges_categories_and_returns_nearest_first():
    kakao = FakeKakao()
    with make_client(kakao) as client:
        response = client.get("/api/places/at", params=PRESS)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    # 설정한 분류마다 같은 좌표·반경으로 한 번씩 부른다.
    assert sorted(kakao.calls) == [("AT4", 35.15, 129.12, 100), ("CE7", 35.15, 129.12, 100)]
    body = response.json()
    # 중복을 뺀 3곳 중 가까운 2곳(nearby_max_results)을 돌려준다.
    assert body["nearbyCount"] == 3
    assert [place["kakaoPlaceId"] for place in body["places"]] == ["900000001", "900000002"]
    park, cafe = body["places"]
    # 검색(API-003)과 같은 매칭·배지를 붙인다. 카카오 장소 URL 은 표준 형식으로 만든다.
    assert (park["placeId"], park["badge"]) == ("public-park", "DETAIL")
    assert (cafe["placeId"], cafe["badge"], cafe["hoursStatus"]) == (None, "BASIC", "NEEDS_CHECK")
    assert cafe["placeUrl"] == "https://place.map.kakao.com/900000002"


def test_no_places_nearby():
    with make_client(FakeKakao(by_code={})) as client:
        response = client.get("/api/places/at", params=PRESS)

    assert response.status_code == 200
    assert response.json() == {"places": [], "nearbyCount": 0}


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"lat": 35.15},
        {"lng": 129.12},
        {"lat": 91, "lng": 129.12},
        {"lat": 35.15, "lng": 181},
        {"lat": "nan", "lng": 129.12},
        {"lat": "inf", "lng": 129.12},
        {"lat": "북위", "lng": 129.12},
    ],
)
def test_invalid_coordinates_are_400_without_calling_kakao(params):
    kakao = FakeKakao()
    with make_client(kakao) as client:
        response = client.get("/api/places/at", params=params)

    assert response.status_code == 400
    assert response.json()["error"]["id"] == "ERR-001"
    assert kakao.calls == []


def test_any_category_failure_is_err_003_without_leaking_coordinates(caplog):
    with caplog.at_level(logging.DEBUG), make_client(FakeKakao(fail_code="CE7")) as client:
        response = client.get("/api/places/at", params={"lat": 35.1234567, "lng": 129.1765432})

    # 일부 분류만 보여 주면 '주변에 없음'으로 오해하므로 전체를 실패로 본다.
    assert response.status_code == 503
    assert response.json()["error"]["id"] == "ERR-003"
    assert response.headers["cache-control"] == "no-store"
    for leaked in ("35.1234567", "129.1765432"):
        assert leaked not in response.text
        assert leaked not in caplog.text


def test_at_is_not_taken_as_place_id_and_needs_kakao_key():
    # 카카오 키가 없으면 장소 상세(/{place_id})의 404 가 아니라 검색 서비스 미구성 503 이다.
    with TestClient(create_app(Settings(app_name="Backend test"))) as client:
        response = client.get("/api/places/at", params=PRESS)

    assert (response.status_code, response.json()["error"]["id"]) == (503, "ERR-017")
