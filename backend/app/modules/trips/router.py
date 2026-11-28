"""API-006~011 with explicitly injected providers.

- API-006 블록 추가, API-007 블록 편집(isFixed·seq·stayMin 중 하나), API-008 블록 삭제는
  `{schedule, violations}` 를 돌려주고 편집 전 상태를 1단계 되돌리기 스냅샷으로 남긴다.
- API-009 일정 생성·검증은 스냅샷을 남기지 않는다.
- API-010 되돌리기는 직전 편집 전 상태를 다시 계산하지 않고 복원해 `{schedule}` 을 돌려준다.
- API-011 경유지 후보 제안. 후보 계산이 끝난 뒤 이유 문구만 LLM 으로 다듬는다(실패하면 규칙 문구, ERR-002).

DELETE·undo 본문은 선택이며 카카오 좌표(`sessionCoords`)만 담는다. 모든 응답은 `Cache-Control: no-store` 이고
오류 메시지에는 요청 값을 넣지 않는다.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.concurrency import run_in_threadpool

from app.modules.ai.waypoint_reason import WaypointReasonService, build_waypoint_reason_service
from app.modules.engine.service import (
    EngineInputError,
    NeedsConfirmationError,
    PolicyRequiredError,
    SequenceNormalizationRequiredError,
)
from app.modules.plan_b.schemas import ApplyPlanBRequest, PlanBResponse
from app.modules.trips.commands import FixedWindowRequiredError
from app.modules.trips.edit_history import NothingToUndoError
from app.modules.trips.schemas import (
    AddBlockRequest,
    DeleteBlockRequest,
    GenerateScheduleRequest,
    InitialScheduleResponse,
    Schedule,
    ScheduleMutationResponse,
    SuggestWaypointsRequest,
    SuggestWaypointsResponse,
    TripDetailResponse,
    UndoRequest,
    UndoResponse,
    UpdateBlockRequest,
)
from app.modules.trips.service import (
    ConcurrentEditError,
    FixedScheduleConflictError,
    InitialScheduleExistsError,
    StayDurationRequiredError,
    TripNotFoundError,
    TripService,
)

router = APIRouter(prefix="/trips", tags=["trips"])
logger = logging.getLogger(__name__)
# PostgreSQL SQLSTATE: lock_timeout 초과(lock_not_available), statement_timeout 초과(query_canceled).
DB_TIMEOUT_KINDS = {"55P03": "lock_timeout", "57014": "statement_timeout"}


class TripAPIError(Exception):
    def __init__(self, status: int, error_id: str, message: str, *, fields: dict[str, str] | None = None) -> None:
        self.status = status
        self.error_id = error_id
        self.message = message
        # ERR-001 의 항목별 오류(요청 필드명 → 안내 문구). 프런트 ApiError.fields 와 같은 형식, 요청 값은 넣지 않는다.
        self.fields = fields


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
        message = "고정 장소의 지정 시각을 지킬 수 없습니다. 날짜 분리를 검토해 주세요."
        # 최초 생성만 충돌한 선택을 `selections.<clientId>` 키로 싣는다(ERR-001 fields 와 같은 키 → 문구 형식).
        fields = {f"selections.{client_id}": message for client_id in exc.client_ids} or None
        return TripAPIError(409, "ERR-009", message, fields=fields)
    if isinstance(exc, NothingToUndoError):
        # SDD 8장에 '되돌릴 편집 없음' 전용 ID 가 없어 ERR-001 을 쓴다. 프런트 ERROR_CATALOG·mock 과 같게 400 이다.
        return TripAPIError(400, "ERR-001", "되돌릴 직전 편집이 없습니다.")
    if isinstance(exc, FixedWindowRequiredError):
        return TripAPIError(
            400, "ERR-001", "지정 시각이 없는 장소는 고정할 수 없습니다. 고정 장소로 다시 추가해 주세요."
        )
    if isinstance(exc, SequenceNormalizationRequiredError):
        return TripAPIError(400, "ERR-001", "기존 일정의 순서값을 별도 정규화한 뒤 다시 편집해 주세요.")
    if isinstance(exc, EngineInputError):
        return TripAPIError(400, "ERR-001", "블록 식별자·순서·삽입 구간 또는 dayNo를 확인해 주세요.")
    if isinstance(exc, StayDurationRequiredError):
        # SDD 8장에 전용 ID 가 없어 ERR-001 을 쓰고, fields.stayMin 으로 '체류시간 입력 필요'를 구분한다.
        message = "체류시간을 정할 수 없는 장소예요. 머무를 시간을 골라 주세요."
        return TripAPIError(400, "ERR-001", message, fields={"stayMin": message})
    if isinstance(exc, InitialScheduleExistsError):
        message = "기존 일정이 있어 최초 자동 생성으로 덮어쓸 수 없습니다."
        return TripAPIError(400, "ERR-001", message, fields={"initial": message})
    if isinstance(exc, PolicyRequiredError):
        return TripAPIError(
            400, "ERR-001", "명시적 삽입 구간·시작 시각·체류시간이 필요하며 자동 배치 옵션은 지원하지 않습니다."
        )
    if isinstance(exc, ConcurrentEditError):
        return TripAPIError(503, "ERR-017", "다른 편집과 겹쳤습니다. 잠시 후 다시 시도해 주세요.")
    if isinstance(exc, NeedsConfirmationError):
        return TripAPIError(503, "ERR-017", "일정 계산에 필요한 장소·경로 정보를 확인해 주세요.")
    if isinstance(exc, OperationalError | PoolTimeoutError):
        # 종류만 남긴다. str(exc) 에는 SQL 문과 바인드 값(일정 데이터)이 들어 있다.
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        kind = (
            "pool_timeout"
            if isinstance(exc, PoolTimeoutError)
            else DB_TIMEOUT_KINDS.get(sqlstate or "", "operational_error")
        )
        cause = type(getattr(exc, "orig", None) or exc).__name__
        logger.warning("trip_db_unavailable kind=%s cause=%s sqlstate=%s", kind, cause, sqlstate)
        return TripAPIError(503, "ERR-017", "저장소가 바빠 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.")
    return TripAPIError(503, "ERR-017", "일정 계산을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.")


@router.get("/{trip_id}/plan-b", response_model=PlanBResponse)
def get_plan_b(
    trip_id: str,
    response: Response,
    service: Service,
    block_id: Annotated[str, Query(alias="blockId", min_length=1, max_length=64)],
) -> PlanBResponse:
    """API-014 플랜 B 3안 조회(FR-010). 조건이 아니면 trigger 가 null 이고 options 가 비어 있다. 저장하지 않는다."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return service.plan_b(trip_id, block_id)
    except Exception as exc:
        raise translate_error(exc) from None


@router.post("/{trip_id}/plan-b/apply", response_model=ScheduleMutationResponse)
def apply_plan_b(
    trip_id: str, body: ApplyPlanBRequest, response: Response, service: Service
) -> ScheduleMutationResponse:
    """API-015 고른 안 적용. 강행(KEEP)은 일정을 그대로 두고, 나머지는 편집 한 번으로 저장해 되돌릴 수 있다."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return service.apply_plan_b(trip_id, body)
    except Exception as exc:
        raise translate_error(exc) from None


@router.get("/{trip_id}", response_model=TripDetailResponse)
def get_trip(trip_id: str, response: Response, service: Service) -> TripDetailResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return service.detail(trip_id)
    except Exception as exc:
        raise translate_error(exc) from None


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


@router.post("/{trip_id}/schedule", response_model=InitialScheduleResponse | Schedule)
def generate_schedule(
    trip_id: str, body: GenerateScheduleRequest, response: Response, service: Service
) -> InitialScheduleResponse | Schedule:
    response.headers["Cache-Control"] = "no-store"
    try:
        return service.generate(trip_id, body)
    except Exception as exc:
        raise translate_error(exc) from None


def waypoint_reason_service(request: Request) -> WaypointReasonService:
    """주입한 서비스가 없으면 환경 설정(GEMINI_*)으로 한 번 만들어 재사용한다. 키가 없으면 규칙 문구 그대로다."""
    service = getattr(request.app.state, "waypoint_reason_service", None)
    if not isinstance(service, WaypointReasonService):
        service = build_waypoint_reason_service()
        request.app.state.waypoint_reason_service = service
    return service


Explainer = Annotated[WaypointReasonService, Depends(waypoint_reason_service)]


@router.post("/{trip_id}/waypoints/suggest", response_model=SuggestWaypointsResponse)
async def suggest_waypoints(
    trip_id: str, body: SuggestWaypointsRequest, response: Response, service: Service, explainer: Explainer
) -> SuggestWaypointsResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        # 후보 계산(엔진·경로 조회)은 동기 코드라 스레드에서 돌린다. 이유 문구는 그 결과만 받는다(AI-REQ-03).
        result = await run_in_threadpool(service.suggest, trip_id, body)
    except Exception as exc:
        raise translate_error(exc) from None
    # 설명 단계는 예외를 던지지 않고, 실패하면 규칙 문구 그대로다(ERR-002). 오류 변환(503)을 거치지 않는 것이 맞다.
    return await explainer.explain(result)
