import logging
from typing import Protocol

from anyio import to_thread

from app.adapters.kakao import KakaoPlace

from .api_schemas import Coords, PlaceSearchItem, PlaceSearchResponse
from .badge import hours_status, place_badge
from .matcher import PlaceMatcher
from .schemas import PublicPlace
from .settings import PlaceMatchSettings

logger = logging.getLogger(__name__)

# 카카오 로컬 API 의 카테고리 그룹 코드(공식 문서 기준)
KAKAO_CATEGORY_GROUP_CODES = frozenset(
    {"MT1", "CS2", "PS3", "SC4", "AC5", "PK6", "OL7", "SW8", "BK9", "CT1", "AG2", "PO3", "AT4", "AD5", "FD6", "CE7"}
    | {"HP8", "PM9"}
)


class InvalidSearchRequestError(Exception):
    """검색어나 분류가 올바르지 않다. API 계층에서 ERR-001(400)로 바꾼다. 입력값은 담지 않는다."""


class PlaceLookupError(Exception):
    """공공 DB 조회 실패. API 계층에서 ERR-017(503)로 바꾼다. 원래 예외는 연결하지 않는다."""


class KakaoPlaceSearch(Protocol):
    """장소 검색 공급자. `KakaoLocalAdapter` 가 구현한다."""

    async def search_keyword(self, query: str, *, category_group_code: str | None = None) -> list[KakaoPlace]: ...


class PlaceSearchService:
    """장소 검색(API-003): 카카오에서 찾고 결과마다 공공 DB 매칭과 배지를 붙인다.

    요청마다 카카오를 호출하며 결과를 저장·캐시하지 않는다(ADR-005, D6).
    """

    def __init__(self, kakao: KakaoPlaceSearch, matcher: PlaceMatcher, settings: PlaceMatchSettings) -> None:
        self._kakao = kakao
        self._matcher = matcher
        self._settings = settings

    async def search(self, query: str, category: str | None = None) -> PlaceSearchResponse:
        query = query.strip()
        if not query or len(query) > self._settings.search_query_max_length:
            raise InvalidSearchRequestError
        if category is not None and category not in KAKAO_CATEGORY_GROUP_CODES:
            raise InvalidSearchRequestError

        places = await self._kakao.search_keyword(query, category_group_code=category)
        # 매칭은 동기 DB 조회라 이벤트 루프를 막지 않도록 스레드에서 한 번에 처리한다.
        failure = ""
        matches: list[PublicPlace | None] = []
        try:
            matches = await to_thread.run_sync(self._match_all, places)
        except Exception as error:
            # DB 오류 문구에는 조회에 쓴 카카오 좌표가 담길 수 있어 종류만 남기고, except 밖에서 새 예외를 던진다.
            failure = type(error).__name__
        if failure:
            logger.warning("place_lookup failed error=%s count=%d", failure, len(places))
            raise PlaceLookupError
        return PlaceSearchResponse(
            places=tuple(_to_item(place, matched) for place, matched in zip(places, matches, strict=True))
        )

    def _match_all(self, places: list[KakaoPlace]) -> list[PublicPlace | None]:
        return [self._matcher.match(place) for place in places]


def _to_item(place: KakaoPlace, matched: PublicPlace | None) -> PlaceSearchItem:
    return PlaceSearchItem(
        place_id=matched.id if matched else None,
        kakao_place_id=place.kakao_place_id,
        place_url=f"https://place.map.kakao.com/{place.kakao_place_id}",
        name=place.name,
        coords=Coords(lat=place.lat, lng=place.lng),
        category=matched.category if matched else _last_category(place.category_name),
        address=place.road_address or place.address or None,
        badge=place_badge(matched),
        hours_status=hours_status(matched),
    )


def _last_category(category_name: str) -> str | None:
    """'여행 > 공원' 에서 '공원'"""
    return category_name.rsplit(">", 1)[-1].strip() or None
