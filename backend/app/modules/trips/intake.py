"""여행 조건 입력 API(FR-002): API-001 한 줄 해석, API-002 여행 생성.

기존 trips 라우터(API-006~011)와 파일을 나눠, 편집 API 작업과 충돌하지 않게 했다.
"""

import secrets
from datetime import date
from typing import Annotated, Literal, Self
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, model_validator

from app.modules.ai.interpret import Conditions, InterpretService, build_interpret_service
from app.modules.ai.sanitizer import InvalidInputError
from app.modules.engine.schemas import ContractModel, LocalTime, ScheduleState, TripWindow
from app.modules.trips.repository import TripRecord
from app.modules.trips.router import Service, TripAPIError

router = APIRouter(prefix="/trips", tags=["trips"])

# 서비스 대상이 부산 1~3일 여행이라(README) 그보다 긴 기간은 받지 않는다.
# 잠정값: SRS 에 상한이 없어 프런트 UI-01 의 검증(MAX_TRIP_DAYS)과 같은 값으로 두었다.
MAX_TRIP_DAYS = 3
BUDGET_MAX = 2_000_000_000  # SDD 5.2 trips.budget(INT)

Mode = Literal["TRANSIT", "CAR", "WALK"]


# ---------- API-001 ----------


class InterpretRequest(ContractModel):
    # 길이·형식은 InputSanitizer 가 검증해 사용자 문구로 알린다. 여기서는 과도한 본문만 막는다.
    text: str = Field(max_length=2000)


class TripDates(ContractModel):
    start: date
    end: date


class InterpretedConditions(ContractModel):
    """해석된 항목만 담는다. 나머지는 사용자가 화면에서 채운다."""

    dates: TripDates | None = None
    day_start: LocalTime | None = None
    day_end: LocalTime | None = None
    mode: Mode | None = None
    companions: str | None = None
    budget: int | None = None


class InterpretResponse(ContractModel):
    conditions: InterpretedConditions
    needs_form: bool


def interpret_service(request: Request) -> InterpretService:
    """주입한 서비스가 없으면 환경 설정(GEMINI_*)으로 한 번 만들어 재사용한다."""
    service = getattr(request.app.state, "interpret_service", None)
    if not isinstance(service, InterpretService):
        service = build_interpret_service()
        request.app.state.interpret_service = service
    return service


Interpreter = Annotated[InterpretService, Depends(interpret_service)]


def _to_response(conditions: Conditions, needs_form: bool) -> InterpretResponse:
    dates = TripDates(start=conditions.start, end=conditions.end) if conditions.start and conditions.end else None
    return InterpretResponse(
        conditions=InterpretedConditions(
            dates=dates,
            day_start=conditions.day_start,
            day_end=conditions.day_end,
            mode=conditions.mode,
            companions=conditions.companions,
            budget=conditions.budget,
        ),
        needs_form=needs_form,
    )


@router.post("/interpret", response_model=InterpretResponse, response_model_exclude_none=True)
async def interpret_conditions(body: InterpretRequest, response: Response, service: Interpreter) -> InterpretResponse:
    """한 줄 문장을 여행 조건으로 해석한다. LLM 이 실패해도 규칙 해석 결과로 200 을 돌려준다(ERR-002)."""
    response.headers["Cache-Control"] = "no-store"
    # 원래 예외나 입력값을 오류에 싣지 않는다. 문장이 로그·응답에 남지 않게 한다.
    try:
        result = await service.interpret(body.text)
    except InvalidInputError:
        raise TripAPIError(
            400, "ERR-001", "입력할 수 없는 내용이에요. 여행 날짜와 이동수단을 짧게 적어 주세요."
        ) from None
    return _to_response(result.conditions, result.needs_form)


# ---------- API-002 ----------


class TripPreferences(ContractModel):
    tags: tuple[Annotated[str, Field(min_length=1, max_length=30)], ...] = Field(default=(), max_length=15)
    avoid: tuple[Annotated[str, Field(min_length=1, max_length=50)], ...] = Field(default=(), max_length=15)
    note: str | None = Field(default=None, max_length=200)


class CreateTripRequest(ContractModel):
    dates: TripDates
    day_start: LocalTime
    day_end: LocalTime
    mode: Mode
    companions: str | None = Field(default=None, max_length=50)
    prefs: TripPreferences | None = None
    budget: int | None = Field(default=None, ge=0, le=BUDGET_MAX)
    start_place_id: str | None = Field(default=None, min_length=1, max_length=64)
    end_place_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_ranges(self) -> Self:
        days = (self.dates.end - self.dates.start).days + 1
        if days < 1 or days > MAX_TRIP_DAYS:
            raise ValueError("trip length out of range")
        if self.day_start >= self.day_end:
            raise ValueError("dayEnd must be after dayStart")
        return self


class CreateTripResponse(ContractModel):
    trip_id: str
    session_key: str


@router.post("", response_model=CreateTripResponse, status_code=201)
def create_trip(body: CreateTripRequest, response: Response, service: Service) -> CreateTripResponse:
    """여행을 만들고 빈 일정에서 시작한다. 장소는 이어지는 API-006 으로 담는다.

    잠정 사항(현재 저장 모델 `TripRecord` 의 한계):
    - 일정 계산에 쓰는 날짜·하루 일정·이동수단(`TripWindow`)만 저장한다. 동행·취향·예산·시작/종료 위치는
      형식만 검증하고 저장하지 않는다. trips 테이블(SDD 5.2)이 들어오면 함께 저장한다.
    - 세션 키는 발급만 하고 이후 요청에서 검증하지 않는다. 전달·보관·검증 방식이 정해지면 붙인다.
    """
    response.headers["Cache-Control"] = "no-store"
    trip = TripWindow(
        start_date=body.dates.start,
        end_date=body.dates.end,
        day_start=body.day_start,
        day_end=body.day_end,
        transport_mode=body.mode,
    )
    trip_id = str(uuid4())
    # 새 ID 에 처음 쓰는 것이라 읽고-고쳐-쓰는 구간이 없다. 편집용 잠금은 필요 없다.
    service.repository.save(trip_id, TripRecord(trip, ScheduleState()))
    return CreateTripResponse(trip_id=trip_id, session_key=secrets.token_urlsafe(32))
