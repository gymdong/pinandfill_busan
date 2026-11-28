"""API-017 사진으로 장소 찾기(FR-012). multipart `image` 하나. 응답은 `Cache-Control: no-store`.

사진은 요청 처리 중 메모리에만 있다. 저장·로그하지 않고, 오류에도 사진·파일명을 넣지 않는다(NFR-006, ERR-014).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile

from app.modules.engine.schemas import ContractModel
from app.modules.photo.service import InvalidPhotoError, PhotoSearchService, PhotoUnavailableError
from app.modules.places.router import PlaceAPIError
from app.modules.recommend.mood_router import MoodPlaceSummary

router = APIRouter(prefix="/places", tags=["places"])


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


@router.post("/photo-search", response_model=PhotoSearchResponse)
async def photo_search(
    response: Response, service: Service, image: Annotated[UploadFile, File()]
) -> PhotoSearchResponse:
    response.headers["Cache-Control"] = "no-store"
    limit = service.settings.max_bytes
    # 상한 + 1 바이트까지만 읽어 큰 파일을 메모리에 다 올리지 않는다.
    data = await image.read(limit + 1)
    media_type = (image.content_type or "").lower()
    await image.close()
    try:
        matches, not_found = await service.search(data, media_type)
    except InvalidPhotoError as error:
        raise PlaceAPIError(
            error.status, "ERR-014", "사진 형식이나 크기를 확인해 주세요. JPG·PNG·WEBP, 5MB 이하예요."
        ) from None
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
