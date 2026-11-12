"""Dependency and engine interfaces; concrete providers arrive later."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Protocol, runtime_checkable

from app.modules.engine.schemas import (
    CalculationContext,
    InsertInput,
    PlaceRef,
    RecomputeInput,
    RouteTimeSemantics,
    ScheduleState,
    TransientPlaceDetails,
    ValidateInput,
    ValidationResult,
)
from app.modules.trips.schemas import Schedule


@dataclass(frozen=True, slots=True)
class RouteEstimate:
    duration_min: int | None
    source: Literal["TMAP", "ODSAY", "CACHE", "ESTIMATED", "UNKNOWN"]
    computed_at: datetime
    time_semantics: RouteTimeSemantics = "unspecified"
    lookup_failed: bool = False


@runtime_checkable
class PlaceDataProvider(Protocol):
    """Request-scoped place lookup, replaceable by fakes in engine tests."""

    def get(self, place_ref: PlaceRef, *, on_date: date) -> TransientPlaceDetails: ...


@runtime_checkable
class RouteProvider(Protocol):
    """Route lookup boundary, replaceable by a deterministic fake."""

    def estimate(
        self,
        origin: TransientPlaceDetails,
        destination: TransientPlaceDetails,
        *,
        mode: Literal["TRANSIT", "CAR", "WALK"],
    ) -> RouteEstimate: ...


@runtime_checkable
class DepartureAwareRouteProvider(Protocol):
    """Optional extension; older deterministic test providers keep estimate()."""

    def estimate_at(
        self,
        origin: TransientPlaceDetails,
        destination: TransientPlaceDetails,
        *,
        mode: Literal["TRANSIT", "CAR", "WALK"],
        departure_at: datetime,
    ) -> RouteEstimate: ...


@dataclass(frozen=True, slots=True)
class EngineResult:
    state: ScheduleState
    schedule: Schedule = field(repr=False)


class ItineraryEngine(Protocol):
    def insert(self, command: InsertInput, *, context: CalculationContext | None = None) -> EngineResult: ...

    def recompute(self, command: RecomputeInput, *, context: CalculationContext | None = None) -> EngineResult: ...

    def validate(self, command: ValidateInput, *, context: CalculationContext | None = None) -> ValidationResult: ...
