"""API-012: 장소별 시간대 예상 혼잡 조회."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from .schemas import PlaceCrowdResponse
from .service import CrowdService

router = APIRouter(prefix="/places", tags=["crowd"])


def get_crowd_service(request: Request) -> CrowdService:
    """앱에 주입된 서비스가 있으면 사용하고, 없으면 기본 서비스 사용."""
    service = getattr(request.app.state, "crowd_service", None)
    if isinstance(service, CrowdService):
        return service
    return CrowdService()


@router.get(
    "/{place_id}/crowd",
    response_model=PlaceCrowdResponse,
)
def get_place_crowd(
    place_id: str,
    request: Request,
    response: Response,
    visit_date: Annotated[date | None, Query(alias="date")] = None,
) -> PlaceCrowdResponse:
    """선택한 장소와 날짜의 예상 혼잡 정보를 조회한다."""
    response.headers["Cache-Control"] = "no-store"

    service = get_crowd_service(request)
    return service.get(place_id, visit_date)
