"""Trip facade for explicitly positioned edits and already anchored schedules."""

from collections.abc import Callable
from threading import RLock

from app.modules.engine.interfaces import EngineResult, ItineraryEngine
from app.modules.engine.schemas import RecomputeInput, ScheduleState
from app.modules.engine.service import NeedsConfirmationError, PolicyRequiredError
from app.modules.recommend.waypoints import WaypointRecommender
from app.modules.trips.commands import calculation_context, insert_command
from app.modules.trips.repository import TripRecord, TripRepository
from app.modules.trips.schemas import (
    AddBlockRequest,
    GenerateScheduleRequest,
    KakaoPlaceKey,
    PublicPlaceInput,
    Schedule,
    ScheduleMutationResponse,
    SuggestWaypointsRequest,
    SuggestWaypointsResponse,
)


class TripNotFoundError(Exception):
    pass


class FixedScheduleConflictError(Exception):
    """No payload attached: request coordinates must never escape through errors."""


class TripService:
    def __init__(
        self,
        repository: TripRepository,
        engine: ItineraryEngine,
        stay_duration: Callable[[PublicPlaceInput | KakaoPlaceKey], int | None],
        *,
        recommender: WaypointRecommender | None = None,
    ) -> None:
        self.repository = repository
        self.engine = engine
        self.stay_duration = stay_duration
        self.recommender = recommender
        # Serializes edits of this local Fake service, including read/compute/save.
        # A database implementation must replace this with transactional concurrency.
        self._lock = RLock()

    def suggest(self, trip_id: str, request: SuggestWaypointsRequest) -> SuggestWaypointsResponse:
        with self._lock:
            record = self._get(trip_id)
            if self.recommender is None:
                raise NeedsConfirmationError("Waypoint providers are not configured")
            return self.recommender.suggest(record, request, calculation_context(request))

    def _get(self, trip_id: str) -> TripRecord:
        record = self.repository.get(trip_id)
        if record is None:
            raise TripNotFoundError
        return record

    def _save(self, trip_id: str, record: TripRecord, result: EngineResult) -> Schedule:
        timing_errors = {
            "TRAVEL_TIME_CONFLICT",
            "FIXED_TIME_CONFLICT",
            "STAY_CONFLICT",
            "DAY_WINDOW_CONFLICT",
            "TIME_WINDOW_UNSUPPORTED",
        }
        if any(
            block.is_fixed and any(warning.type in timing_errors for warning in block.warnings)
            for day in result.schedule.days
            for block in day.blocks
        ):
            raise FixedScheduleConflictError
        self.repository.save(trip_id, TripRecord(record.trip, result.state))
        return result.schedule

    def insert(self, trip_id: str, request: AddBlockRequest) -> ScheduleMutationResponse:
        with self._lock:
            record = self._get(trip_id)
            stay = self.stay_duration(request.place)
            if stay is None:
                raise PolicyRequiredError("Stay duration needs an agreed source")
            command = insert_command(request, record.trip, record.schedule, stay_min=stay)
            result = self.engine.insert(command, context=calculation_context(request))
            schedule = self._save(trip_id, record, result)
            return ScheduleMutationResponse(schedule=schedule, violations=schedule.violations)

    def generate(self, trip_id: str, request: GenerateScheduleRequest) -> Schedule:
        with self._lock:
            record = self._get(trip_id)
            if request.options:
                raise PolicyRequiredError("Generation options need an agreed policy")
            if not record.schedule.blocks:
                raise PolicyRequiredError("Initial automatic placement needs an agreed policy")
            blocks = list(record.schedule.blocks)
            anchors: list[str] = []
            for index, block in enumerate(blocks):
                if index and blocks[index - 1].day_no == block.day_no:
                    continue
                if block.is_fixed and block.fixed_start is not None and block.fixed_end is not None:
                    block = block.model_copy(update={"arrive_at": block.fixed_start, "depart_at": block.fixed_end})
                    blocks[index] = block
                if block.arrive_at is None or block.depart_at is None:
                    raise PolicyRequiredError("Each day needs an explicitly timed first block")
                anchors.append(block.id)
            state = ScheduleState(blocks=tuple(blocks), legs=record.schedule.legs)
            context = calculation_context(request)
            result: EngineResult
            for anchor in anchors:
                result = self.engine.recompute(
                    RecomputeInput(trip=record.trip, schedule=state, from_block_id=anchor),
                    context=context,
                )
                state = result.state
            return self._save(trip_id, record, result)
