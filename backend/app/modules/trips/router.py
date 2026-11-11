"""API-006, API-009 and API-011 with explicitly injected providers."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.modules.engine.service import (
    EngineInputError,
    NeedsConfirmationError,
    PolicyRequiredError,
    SequenceNormalizationRequiredError,
)
from app.modules.trips.schemas import (
    AddBlockRequest,
    GenerateScheduleRequest,
    Schedule,
    ScheduleMutationResponse,
    SuggestWaypointsRequest,
    SuggestWaypointsResponse,
)
from app.modules.trips.service import FixedScheduleConflictError, TripNotFoundError, TripService

router = APIRouter(prefix="/trips", tags=["trips"])


class TripAPIError(Exception):
    def __init__(self, status: int, error_id: str, message: str) -> None:
        self.status = status
        self.error_id = error_id
        self.message = message


def trip_service(request: Request) -> TripService:
    service = request.app.state.trip_service
    if not isinstance(service, TripService):
        raise TripAPIError(503, "ERR-017", "일정 서비스가 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.")
    return service


Service = Annotated[TripService, Depends(trip_service)]


def translate_error(exc: Exception) -> TripAPIError:
    # Never use str(exc), errors(), or the original body: they may contain search data.
    if isinstance(exc, TripNotFoundError):
        return TripAPIError(404, "ERR-016", "여행을 찾을 수 없습니다.")
    if isinstance(exc, FixedScheduleConflictError):
        return TripAPIError(409, "ERR-009", "고정 장소의 지정 시각을 지킬 수 없습니다. 날짜 분리를 검토해 주세요.")
    if isinstance(exc, SequenceNormalizationRequiredError):
        return TripAPIError(400, "ERR-001", "기존 일정의 순서값을 별도 정규화한 뒤 다시 편집해 주세요.")
    if isinstance(exc, EngineInputError):
        return TripAPIError(400, "ERR-001", "블록 식별자·순서·삽입 구간 또는 dayNo를 확인해 주세요.")
    if isinstance(exc, PolicyRequiredError):
        return TripAPIError(
            400, "ERR-001", "명시적 삽입 구간·시작 시각·체류시간이 필요하며 자동 배치 옵션은 지원하지 않습니다."
        )
    if isinstance(exc, NeedsConfirmationError):
        return TripAPIError(503, "ERR-017", "일정 계산에 필요한 장소·경로 정보를 확인해 주세요.")
    return TripAPIError(503, "ERR-017", "일정 계산을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.")


@router.post("/{trip_id}/blocks", response_model=ScheduleMutationResponse)
def add_block(trip_id: str, body: AddBlockRequest, response: Response, service: Service) -> ScheduleMutationResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return service.insert(trip_id, body)
    except Exception as exc:
        raise translate_error(exc) from None


@router.post("/{trip_id}/schedule", response_model=Schedule)
def generate_schedule(trip_id: str, body: GenerateScheduleRequest, response: Response, service: Service) -> Schedule:
    response.headers["Cache-Control"] = "no-store"
    try:
        return service.generate(trip_id, body)
    except Exception as exc:
        raise translate_error(exc) from None


@router.post("/{trip_id}/waypoints/suggest", response_model=SuggestWaypointsResponse)
def suggest_waypoints(
    trip_id: str, body: SuggestWaypointsRequest, response: Response, service: Service
) -> SuggestWaypointsResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return service.suggest(trip_id, body)
    except Exception as exc:
        raise translate_error(exc) from None
