"""API-003 장소 검색, API-005 장소 상세. 서비스는 앱 생성 시 주입한다(app.main 기본 구성).

`/{place_id}` 는 모든 한 단계 경로를 받으므로 `/search`·`/at` 같은 고정 경로는 그보다 먼저 등록한다.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from app.adapters.kakao import KakaoLocalError

from .api_schemas import PlaceDetailResponse, PlaceSearchResponse
from .detail import PlaceDetailService, PlaceNotFoundError
from .service import InvalidSearchRequestError, PlaceLookupError, PlaceSearchService

router = APIRouter(prefix="/places", tags=["places"])


class PlaceAPIError(Exception):
    def __init__(self, status: int, error_id: str, message: str) -> None:
        self.status = status
        self.error_id = error_id
        self.message = message


def place_search_service(request: Request) -> PlaceSearchService:
    service = getattr(request.app.state, "place_search_service", None)
    if not isinstance(service, PlaceSearchService):
        raise PlaceAPIError(503, "ERR-017", "장소 검색이 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.")
    return service


Service = Annotated[PlaceSearchService, Depends(place_search_service)]


def place_detail_service(request: Request) -> PlaceDetailService:
    service = getattr(request.app.state, "place_detail_service", None)
    if not isinstance(service, PlaceDetailService):
        raise PlaceAPIError(503, "ERR-017", "장소 정보가 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.")
    return service


DetailService = Annotated[PlaceDetailService, Depends(place_detail_service)]


@router.get("/search", response_model=PlaceSearchResponse)
async def search_places(
    q: str, response: Response, service: Service, category: str | None = None
) -> PlaceSearchResponse:
    response.headers["Cache-Control"] = "no-store"
    # 원래 예외나 입력값을 오류에 싣지 않는다. 검색어가 로그·응답에 남지 않게 한다.
    try:
        return await service.search(q, category)
    except InvalidSearchRequestError:
        raise PlaceAPIError(400, "ERR-001", "검색어와 분류를 확인해 주세요.") from None
    except KakaoLocalError:
        raise PlaceAPIError(503, "ERR-003", "장소 검색이 잠시 안 돼요. 지도에서 직접 골라 주세요.") from None
    except PlaceLookupError:
        raise PlaceAPIError(503, "ERR-017", "장소 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.") from None


# 고정 경로(/search 등)보다 뒤에 둔다. 새 고정 경로(API-004 /at 등)도 이 함수보다 위에 등록한다.
@router.get("/{place_id}", response_model=PlaceDetailResponse)
def get_place(
    place_id: str,
    response: Response,
    service: DetailService,
    on_date: Annotated[date | None, Query(alias="date")] = None,
) -> PlaceDetailResponse:
    """API-005. `date` 는 형식만 검사한다(잘못되면 400 ERR-001). 그날 영업시간은 화면이 요일로 고른다.

    혼잡 요약이 붙으면 `date` 를 기준일로 쓴다.
    """
    response.headers["Cache-Control"] = "no-store"
    try:
        return service.get(place_id)
    except PlaceNotFoundError:
        raise PlaceAPIError(404, "ERR-016", "장소를 찾을 수 없어요.") from None
