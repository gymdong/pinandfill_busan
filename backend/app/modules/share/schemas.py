"""API-019·020 계약(FR-011). 공유 응답은 여행 ID·되돌리기 상태를 담지 않는다."""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime

from app.modules.engine.schemas import ContractModel, LocalTime
from app.modules.trips.schemas import Schedule, TripDates


class ShareTripRequest(ContractModel):
    # 없으면 여행 마지막 날 + 7일(한국 시간)에 닫힌다. 시간대가 있는 시각만 받는다.
    expires_at: AwareDatetime | None = None


class ShareTripResponse(ContractModel):
    # 프런트 기준 경로. 화면이 자기 origin 을 붙여 전체 주소를 만든다.
    url: str
    token: str
    expires_at: datetime | None = None


class SharedTripConditions(ContractModel):
    dates: TripDates
    day_start: LocalTime
    day_end: LocalTime
    mode: Literal["TRANSIT", "CAR", "WALK"]


class SharedTripResponse(ContractModel):
    trip: SharedTripConditions
    schedule: Schedule
