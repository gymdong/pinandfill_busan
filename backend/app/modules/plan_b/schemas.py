"""API-014·015 플랜 B 계약(FR-010). SDD 는 {trigger, options[3]}·{optionId} 만 정한다. 나머지 필드는 잠정이다."""

from typing import Literal

from pydantic import Field

from app.modules.engine.schemas import ContractModel, LocalTime
from app.modules.trips.schemas import CrowdSummary, PlaceSummary, Schedule, Violation, WithSessionCoords

PlanBKind = Literal["KEEP", "REORDER", "REPLACE"]
# CROWD: 예상 '붐빔' 이상·신뢰도 기준 이상. RAIN 은 날씨(FR-013)가 붙으면 쓴다.
PlanBTrigger = Literal["CROWD", "RAIN"]


class PlanBOption(ContractModel):
    id: str
    kind: PlanBKind
    # 이 안을 고를 수 있는가. 고를 수 없으면 `note` 가 이유다(예: 덜 붐비는 순서가 없음).
    available: bool
    # 그 날 총 이동시간의 변화(분, 음수면 줄어듦). 이동시간을 모르는 구간이 있으면 None.
    extra_minutes: int | None
    # 바꾼 뒤 그 날 블록 중 영업시간과 맞지 않는(휴무일·영업시간 밖) 블록이 있는가.
    hours_conflict: bool
    # 대상(또는 대체) 장소의 새 도착·출발 시각과 그 시각의 예상 혼잡.
    arrive_at: LocalTime | None = None
    depart_at: LocalTime | None = None
    crowd: CrowdSummary | None = None
    # REPLACE 의 대체 장소.
    place: PlaceSummary | None = None
    note: str | None = None


class PlanBResponse(ContractModel):
    block_id: str
    # None 이면 플랜 B 를 띄울 조건이 아니다(options 도 비어 있다).
    trigger: PlanBTrigger | None
    # 대상 블록 지금 시각의 예상 혼잡.
    crowd: CrowdSummary | None
    # 안의 이동시간이 직선거리 추정인가(조회는 경로 API 를 부르지 않는다). 적용하면 실제 경로로 다시 계산한다.
    estimated: bool = False
    options: tuple[PlanBOption, ...] = Field(default=(), max_length=3)


class ApplyPlanBRequest(WithSessionCoords):
    option_id: str = Field(min_length=1, max_length=200)


class ApplyPlanBResponse(ContractModel):
    schedule: Schedule
    violations: tuple[Violation, ...] = ()
