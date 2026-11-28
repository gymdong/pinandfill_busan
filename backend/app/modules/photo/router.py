"""API-017 사진으로 장소 찾기(FR-012). multipart `image` 하나. 응답은 `Cache-Control: no-store`.

사진은 저장·로그하지 않고, 오류에도 사진·파일명을 넣지 않는다(NFR-006, ERR-014). Starlette 는 1MB 를 넘는 파트를
이름 없는 임시 파일(만들자마자 unlink)에 받고 요청이 끝나면 닫는다. 본문 전체 크기 상한은 앞단 프록시
(예: nginx client_max_body_size 5m)에서 건다. 화면은 보통 1MB 미만으로 줄여 보낸다.
"""

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile

from app.modules.engine.schemas import ContractModel
from app.modules.photo.service import InvalidPhotoError, PhotoSearchService, PhotoUnavailableError
from app.modules.places.router import PlaceAPIError
from app.modules.recommend.mood_router import MoodPlaceSummary

router = APIRouter(prefix="/places", tags=["places"])
INVALID_MESSAGE = "사진 형식이나 크기를 확인해 주세요. JPG·PNG·WEBP 사진만 찾을 수 있어요."


class PhotoCandidate(ContractModel):
    place: MoodPlaceSummary
    # 0~1. 모델이 판단한 '이 장소에서 찍었을' 확신도(소수 둘째 자리).
    confidence: float


class PhotoSearchResponse(ContractModel):
    candidates: tuple[PhotoCandidate, ...] = ()
    not_found: bool


def photo_service(request: Request) -> PhotoSearchService:
    service = getattr(request.app.state, "photo_service", None)
    if not isinstance(service, PhotoSearchService):
        raise PlaceAPIError(503, "ERR-017", "사진으로 찾기가 지금은 준비되지 않았어요. 장소 이름으로 검색해 주세요.")
    return service


Service = Annotated[PhotoSearchService, Depends(photo_service)]

_recent: dict[str, deque[float]] = defaultdict(deque)
_recent_lock = Lock()


def _allow(client: str, per_minute: int) -> bool:
    """IP 별 최근 1분 요청 수 제한(메모리, 워커마다 따로). 유료 모델 호출 남용을 막는다."""
    now = time.monotonic()
    with _recent_lock:
        stamps = _recent[client]
        while stamps and now - stamps[0] > 60:
            stamps.popleft()
        if len(stamps) >= per_minute:
            return False
        stamps.append(now)
        return True


@router.post("/photo-search", response_model=PhotoSearchResponse)
async def photo_search(
    request: Request, response: Response, service: Service, image: Annotated[UploadFile | None, File()] = None
) -> PhotoSearchResponse:
    response.headers["Cache-Control"] = "no-store"
    if image is None:
        raise PlaceAPIError(400, "ERR-014", INVALID_MESSAGE)
    if not _allow(request.client.host if request.client else "unknown", service.settings.per_minute):
        await image.close()
        raise PlaceAPIError(429, "ERR-017", "사진을 너무 자주 보냈어요. 잠시 후 다시 시도해 주세요.")
    limit = service.settings.max_bytes
    # 상한 + 1 바이트까지만 읽어 큰 파일을 메모리에 다 올리지 않는다.
    data = await image.read(limit + 1)
    media_type = (image.content_type or "").lower()
    await image.close()
    try:
        matches, not_found = await service.search(data, media_type)
    except InvalidPhotoError as error:
        raise PlaceAPIError(error.status, "ERR-014", INVALID_MESSAGE) from None
    except PhotoUnavailableError:
        raise PlaceAPIError(
            503, "ERR-017", "사진을 분석하지 못했어요. 잠시 후 다시 시도하거나 이름으로 검색해 주세요."
        ) from None
    finally:
        del data
    return PhotoSearchResponse(
        candidates=tuple(
            PhotoCandidate(
                place=MoodPlaceSummary(
                    id=match.place.place.id,
                    name=match.place.place.name,
                    lat=match.place.place.lat,
                    lng=match.place.place.lng,
                    category=match.place.place.category,
                    ref_date=match.place.ref_date,
                ),
                confidence=match.confidence,
            )
            for match in matches
        ),
        not_found=not_found,
    )
