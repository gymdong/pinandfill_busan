"""API-003 장소 검색. 서비스는 앱 생성 시 명시적으로 주입한다."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.adapters.kakao import KakaoLocalError

from .api_schemas import PlaceSearchResponse
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
