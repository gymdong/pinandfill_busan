"""HTTP response schemas for trips and API-009."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import Field, HttpUrl, model_validator

from app.modules.engine.schemas import (
    ContractModel,
    FixedWindow,
    KakaoPlaceRef,
    LocalTime,
    ScheduleConflict,
    SessionCoordinate,
    Violation,
)


class PlaceSummary(ContractModel):
    """Transient display projection; this is never an engine persistence model."""

    id: str
    name: str = Field(repr=False)
    lat: float = Field(repr=False, ge=-90, le=90)
    lng: float = Field(repr=False, ge=-180, le=180)
    category: str
    source: Literal["PUBLIC"]
    ref_date: date


class CrowdSummary(ContractModel):
    grade: Literal["여유", "보통", "붐빔", "매우 붐빔"] | None
    confidence: Literal["높음", "중간", "낮음", "없음"]
    as_of: datetime | None
    sources: tuple[str, ...] = ()


class KakaoPlaceKey(ContractModel):
    kakao_place_id: str = Field(pattern=r"^[0-9]+$")
    place_url: HttpUrl

    @model_validator(mode="after")
    def validate_url(self) -> Self:
        KakaoPlaceRef.model_validate({"kakaoPlaceId": self.kakao_place_id, "placeUrl": self.place_url})
        return self


class KakaoBlockPlace(KakaoPlaceKey):
    source: Literal["KAKAO"] = "KAKAO"


BlockPlace = Annotated[PlaceSummary | KakaoBlockPlace, Field(discriminator="source")]


class Block(ContractModel):
    id: str
    day_no: int = Field(ge=1)
    seq: int = Field(ge=0)
    place: BlockPlace
    is_fixed: bool
    fixed_start: LocalTime | None
    fixed_end: LocalTime | None
    stay_min: int = Field(gt=0)
    arrive_at: LocalTime | None
    depart_at: LocalTime | None
    origin: Literal["USER", "SUGGESTED"]
    warnings: tuple[Violation, ...] = ()


class Leg(ContractModel):
    id: str
    from_block_id: str
    to_block_id: str
    mode: Literal["TRANSIT", "CAR", "WALK"]
    duration_min: int | None = Field(default=None, ge=0)
    computed_at: datetime
    source: Literal["TMAP", "ODSAY", "CACHE", "ESTIMATED"]


class BlockCrowd(CrowdSummary):
    block_id: str


class BlockWeather(ContractModel):
    block_id: str
    pop: int | None = Field(default=None, ge=0, le=100)
    pty: str | None
    sky: str | None
    temp: float | None
    wind: float | None
    issued_at: datetime
    scope: Literal["SHORT", "MID"]


class ScheduleDay(ContractModel):
    day_no: int = Field(ge=1)
    date: date
    blocks: tuple[Block, ...] = ()
    legs: tuple[Leg, ...] = ()
    crowd: tuple[BlockCrowd, ...] = ()
    weather: tuple[BlockWeather, ...] = ()


class Schedule(ContractModel):
    """API-009 response body, compatible with the provisional frontend type."""

    days: tuple[ScheduleDay, ...] = ()
    violations: tuple[Violation, ...] = ()
    conflicts: tuple[ScheduleConflict, ...] = ()


class WithSessionCoords(ContractModel):
    session_coords: dict[str, SessionCoordinate] = Field(default_factory=dict, exclude=True, repr=False)


class GenerateScheduleRequest(WithSessionCoords):
    options: dict[str, object] | None = None


class PublicPlaceInput(ContractModel):
    place_id: str = Field(min_length=1)


class AddBlockRequest(WithSessionCoords):
    day_no: int | None = Field(default=None, ge=1)
    place: PublicPlaceInput | KakaoPlaceKey
    is_fixed: bool
    fixed_window: FixedWindow | None = None
    origin: Literal["USER", "SUGGESTED"]
    from_block_id: str | None = None
    to_block_id: str | None = None

    @model_validator(mode="after")
    def paired_slot(self) -> Self:
        if (self.from_block_id is None) != (self.to_block_id is None):
            raise ValueError("fromBlockId and toBlockId must be supplied together")
        if self.from_block_id is not None and self.from_block_id == self.to_block_id:
            raise ValueError("slot endpoints must differ")
        return self


class UpdateBlockRequest(WithSessionCoords):
    """API-007. 프런트 `UpdateBlockRequest` 처럼 isFixed·seq·stayMin 중 정확히 하나만 보낸다."""

    is_fixed: bool | None = None
    seq: int | None = Field(default=None, ge=1)
    stay_min: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def exactly_one_change(self) -> Self:
        if sum(value is not None for value in (self.is_fixed, self.seq, self.stay_min)) != 1:
            raise ValueError("exactly one of isFixed, seq or stayMin is required")
        return self


class DeleteBlockRequest(WithSessionCoords):
    """API-008 본문. 뒤 블록 재계산에 쓸 카카오 좌표만 담으며, 본문 없이 보내도 된다."""


class UndoRequest(WithSessionCoords):
    """API-010 본문. 되돌린 일정의 경고 판정에 쓸 카카오 좌표만 담으며, 본문 없이 보내도 된다."""


class ScheduleMutationResponse(ContractModel):
    schedule: Schedule
    violations: tuple[Violation, ...] = ()


class UndoResponse(ContractModel):
    schedule: Schedule


class SuggestWaypointsRequest(WithSessionCoords):
    from_block_id: str = Field(min_length=1)
    to_block_id: str = Field(min_length=1)
    threshold_min: Literal[10, 15, 30]


class WaypointCandidate(ContractModel):
    place: PlaceSummary
    detour_min: int
    stay_min: int = Field(gt=0)
    crowd: CrowdSummary | None
    reason: str


class SuggestWaypointsResponse(ContractModel):
    candidates: tuple[WaypointCandidate, ...] = Field(default=(), max_length=3)
