"""API-006~011 with explicitly injected providers.

- API-006 블록 추가, API-007 블록 편집(isFixed·seq·stayMin 중 하나), API-008 블록 삭제는
  `{schedule, violations}` 를 돌려주고 편집 전 상태를 1단계 되돌리기 스냅샷으로 남긴다.
- API-009 일정 생성·검증은 스냅샷을 남기지 않는다.
- API-010 되돌리기는 직전 편집 전 상태를 다시 계산하지 않고 복원해 `{schedule}` 을 돌려준다.
- API-011 경유지 후보 제안.

DELETE·undo 본문은 선택이며 카카오 좌표(`sessionCoords`)만 담는다. 모든 응답은 `Cache-Control: no-store` 이고
오류 메시지에는 요청 값을 넣지 않는다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.modules.engine.service import (
    EngineInputError,
    NeedsConfirmationError,
    PolicyRequiredError,
    SequenceNormalizationRequiredError,
)
from app.modules.trips.commands import FixedWindowRequiredError
from app.modules.trips.edit_history import NothingToUndoError
from app.modules.trips.schemas import (
    AddBlockRequest,
    DeleteBlockRequest,
    GenerateScheduleRequest,
    Schedule,
    ScheduleMutationResponse,
    SuggestWaypointsRequest,
    SuggestWaypointsResponse,
    UndoRequest,
    UndoResponse,
    UpdateBlockRequest,
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
    if isinstance(exc, NothingToUndoError):
        # SDD 8장에 '되돌릴 편집 없음' 전용 ID 가 없어 잠정으로 ERR-001 을 쓴다(상태 충돌이므로 409).
        return TripAPIError(409, "ERR-001", "되돌릴 직전 편집이 없습니다.")
    if isinstance(exc, FixedWindowRequiredError):
        return TripAPIError(
            400, "ERR-001", "지정 시각이 없는 장소는 고정할 수 없습니다. 고정 장소로 다시 추가해 주세요."
        )
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


@router.patch("/{trip_id}/blocks/{block_id}", response_model=ScheduleMutationResponse)
def update_block(
    trip_id: str, block_id: str, body: UpdateBlockRequest, response: Response, service: Service
) -> ScheduleMutationResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return service.update_block(trip_id, block_id, body)
    except Exception as exc:
        raise translate_error(exc) from None


@router.delete("/{trip_id}/blocks/{block_id}", response_model=ScheduleMutationResponse)
def delete_block(
    trip_id: str, block_id: str, response: Response, service: Service, body: DeleteBlockRequest | None = None
) -> ScheduleMutationResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return service.delete_block(trip_id, block_id, body or DeleteBlockRequest())
    except Exception as exc:
        raise translate_error(exc) from None


@router.post("/{trip_id}/undo", response_model=UndoResponse)
def undo(trip_id: str, response: Response, service: Service, body: UndoRequest | None = None) -> UndoResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return service.undo(trip_id, body or UndoRequest())
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
