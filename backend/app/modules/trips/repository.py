"""Persistence boundary: accept only reference-based engine state, never requests."""

from dataclasses import dataclass
from typing import Protocol

from app.modules.engine.schemas import ScheduleState, TripWindow


@dataclass(frozen=True)
class TripRecord:
    trip: TripWindow
    schedule: ScheduleState


class TripRepository(Protocol):
    def get(self, trip_id: str) -> TripRecord | None: ...

    def save(self, trip_id: str, record: TripRecord) -> None: ...


class FakeTripRepository:
    """Process-local test storage. Not a production database or shared cache."""

    def __init__(self, records: dict[str, TripRecord]) -> None:
        self._records = dict(records)

    def get(self, trip_id: str) -> TripRecord | None:
        return self._records.get(trip_id)

    def save(self, trip_id: str, record: TripRecord) -> None:
        self._records[trip_id] = record
