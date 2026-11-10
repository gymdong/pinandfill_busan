"""Pure data contracts for the itinerary engine.

Persistent engine state contains opaque place references only.  Display data
obtained from search providers belongs to :class:`TransientPlaceDetails` and is
intentionally excluded from serialization and representation.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    PlainSerializer,
    model_validator,
)


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )


def _minute_precision(value: time) -> time:
    if value.second or value.microsecond or value.tzinfo is not None:
        raise ValueError("time values must use local minute precision without a UTC offset")
    return value


LocalTime = Annotated[
    time,
    AfterValidator(_minute_precision),
    PlainSerializer(lambda value: value.strftime("%H:%M"), return_type=str, when_used="json"),
]


class PublicPlaceRef(ContractModel):
    """Stable reference to a place owned by the public-data database."""

    kind: Literal["PUBLIC"] = "PUBLIC"
    place_id: str = Field(min_length=1)


class KakaoPlaceRef(ContractModel):
    """The complete set of Kakao search data allowed in persistent state."""

    kind: Literal["KAKAO"] = "KAKAO"
    kakao_place_id: str = Field(pattern=r"^[0-9]+$")
    kakao_place_url: HttpUrl = Field(
        alias="placeUrl",
        validation_alias=AliasChoices("placeUrl", "kakaoPlaceUrl", "kakao_place_url"),
    )

    @model_validator(mode="after")
    def validate_canonical_url(self) -> Self:
        expected = f"https://place.map.kakao.com/{self.kakao_place_id}"
        if str(self.kakao_place_url) != expected:
            raise ValueError("placeUrl must be the canonical URL for kakaoPlaceId")
        return self


PlaceRef = Annotated[PublicPlaceRef | KakaoPlaceRef, Field(discriminator="kind")]


class TripWindow(ContractModel):
    start_date: date
    end_date: date
    day_start: LocalTime
    day_end: LocalTime
    transport_mode: Literal["TRANSIT", "CAR", "WALK"]

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("endDate must be on or after startDate")
        return self


class FixedWindow(ContractModel):
    day_no: int = Field(ge=1)
    start: LocalTime
    end: LocalTime


class BlockDraft(ContractModel):
    """Internal insertion draft; stay duration must be explicitly resolved.

    Latest API-006 proposes adjacent anchors. Automatic placement is still
    unspecified and is not implied by this draft.
    """

    place_ref: PlaceRef
    is_fixed: bool
    fixed_window: FixedWindow | None = None
    stay_min: int = Field(gt=0)
    origin: Literal["USER", "SUGGESTED"]


class StoredBlock(ContractModel):
    """Serializable block state; it never contains Kakao name or coordinates."""

    id: str = Field(min_length=1)
    day_no: int = Field(ge=1)
    seq: int = Field(ge=0)
    place_ref: PlaceRef
    is_fixed: bool
    fixed_start: LocalTime | None = None
    fixed_end: LocalTime | None = None
    stay_min: int = Field(gt=0)
    arrive_at: LocalTime | None = None
    depart_at: LocalTime | None = None
    origin: Literal["USER", "SUGGESTED"]


RouteTimeSemantics = Literal["unspecified", "prediction", "service_availability", "search_context", "static"]


class StoredLeg(ContractModel):
    id: str = Field(min_length=1)
    from_block_id: str = Field(min_length=1)
    to_block_id: str = Field(min_length=1)
    mode: Literal["TRANSIT", "CAR", "WALK"]
    duration_min: int | None = Field(default=None, ge=0)
    source: Literal["TMAP", "ODSAY", "CACHE", "ESTIMATED"]
    computed_at: datetime | None = None
    time_semantics: RouteTimeSemantics = "unspecified"
    lookup_failed: bool = False


class ScheduleState(ContractModel):
    """Engine-owned state suitable for persistence or snapshots."""

    blocks: tuple[StoredBlock, ...] = ()
    legs: tuple[StoredLeg, ...] = ()


class OpeningHours(ContractModel):
    """Normalized hours for one date, supplied by the place provider, never parsed here."""

    is_closed: bool = False
    open_time: LocalTime | None = None
    close_time: LocalTime | None = None
    break_start: LocalTime | None = None
    break_end: LocalTime | None = None


class SessionCoordinate(ContractModel):
    lat: float = Field(repr=False, exclude=True, ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(repr=False, exclude=True, ge=-180, le=180, allow_inf_nan=False)


class CalculationContext(ContractModel):
    """Create per call; never attach this object to persistent schedule state."""

    session_coords: dict[str, SessionCoordinate] = Field(default_factory=dict, exclude=True, repr=False)


class TransientPlaceDetails(ContractModel):
    """Request-scoped provider data that must not be dumped, cached or logged."""

    place_ref: PlaceRef
    name: str | None = Field(default=None, repr=False, exclude=True)
    lat: float | None = Field(default=None, repr=False, exclude=True, ge=-90, le=90, allow_inf_nan=False)
    lng: float | None = Field(default=None, repr=False, exclude=True, ge=-180, le=180, allow_inf_nan=False)
    category: str | None = Field(default=None, repr=False, exclude=True)
    ref_date: date | None = Field(default=None, repr=False, exclude=True)
    hours: OpeningHours | None = Field(default=None, repr=False, exclude=True)


class InsertInput(ContractModel):
    trip: TripWindow
    schedule: ScheduleState
    block: BlockDraft
    from_block_id: str | None = None
    to_block_id: str | None = None
    block_id: str | None = None


class RecomputeInput(ContractModel):
    """Recompute from an existing block, per the current SDD contract.

    The representation of a deletion/reorder boundary remains an open design
    question and is deliberately absent from this initial interface.
    """

    trip: TripWindow
    schedule: ScheduleState
    from_block_id: str = Field(min_length=1)


class ValidateInput(ContractModel):
    trip: TripWindow
    schedule: ScheduleState


class Violation(ContractModel):
    type: str = Field(min_length=1)
    cause: str = Field(min_length=1)


class ScheduleConflict(ContractModel):
    cause: str = Field(min_length=1)
    block_ids: tuple[str, ...] = ()


class ValidationResult(ContractModel):
    violations: tuple[Violation, ...] = ()
    conflicts: tuple[ScheduleConflict, ...] = ()
    block_warnings: dict[str, tuple[Violation, ...]] = Field(default_factory=dict)
