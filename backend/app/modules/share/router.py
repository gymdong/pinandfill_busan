"""API-019 공유 링크 만들기, API-020 공유 일정 열람(읽기 전용). 응답은 모두 `Cache-Control: no-store`."""

import re
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.params import Body

from app.modules.share.schemas import SharedTripResponse, ShareTripRequest, ShareTripResponse
from app.modules.share.service import InvalidExpiryError, SharedLinkNotFoundError, ShareService
from app.modules.trips.router import TripAPIError, translate_error

router = APIRouter(tags=["share"])
# 형식이 틀린 토큰(메신저에서 잘린 링크 등)도 없는 링크와 같이 404 로 답한다(존재 여부를 구분하지 않는다).
TOKEN = re.compile(r"[A-Za-z0-9_-]{20,64}")


def share_service(request: Request) -> ShareService:
    service = getattr(request.app.state, "share_service", None)
    if not isinstance(service, ShareService):
        raise TripAPIError(503, "ERR-017", "공유 서비스가 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.")
    return service


Service = Annotated[ShareService, Depends(share_service)]


@router.post("/trips/{trip_id}/share", response_model=ShareTripResponse)
def create_share_link(
    trip_id: str,
    response: Response,
    service: Service,
    body: Annotated[ShareTripRequest | None, Body()] = None,
) -> ShareTripResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return service.share(trip_id, body or ShareTripRequest())
    except InvalidExpiryError:
        raise TripAPIError(400, "ERR-001", "만료 시각은 지금보다 뒤여야 합니다.") from None
    except Exception as exc:
        raise translate_error(exc) from None


@router.get("/shared/{token}", response_model=SharedTripResponse)
def get_shared_trip(
    response: Response,
    service: Service,
    token: str,
) -> SharedTripResponse:
    response.headers["Cache-Control"] = "no-store"
    # 검색 엔진이 공유 일정을 색인하지 않게 한다.
    response.headers["X-Robots-Tag"] = "noindex"
    if TOKEN.fullmatch(token) is None:
        raise TripAPIError(404, "ERR-016", "공유 링크가 없거나 만료되었습니다.")
    try:
        return service.shared(token)
    except SharedLinkNotFoundError:
        raise TripAPIError(404, "ERR-016", "공유 링크가 없거나 만료되었습니다.") from None
    except Exception as exc:
        raise translate_error(exc) from None
