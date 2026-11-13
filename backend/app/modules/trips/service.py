"""Trip facade for explicitly positioned edits and already anchored schedules."""

from collections.abc import Callable
from threading import RLock

from app.modules.engine.interfaces import EngineResult, ItineraryEngine
from app.modules.engine.schemas import CalculationContext, RecomputeInput, ScheduleState, ValidateInput
from app.modules.engine.service import NeedsConfirmationError, PolicyRequiredError
from app.modules.recommend.waypoints import WaypointRecommender
from app.modules.trips.commands import calculation_context, delete_command, insert_command, update_command
from app.modules.trips.edit_history import EditHistory, InMemorySnapshotRepository
from app.modules.trips.repository import TripRecord, TripRepository
from app.modules.trips.schemas import (
    AddBlockRequest,
    DeleteBlockRequest,
    GenerateScheduleRequest,
    KakaoPlaceKey,
    PublicPlaceInput,
    Schedule,
    ScheduleMutationResponse,
    SuggestWaypointsRequest,
    SuggestWaypointsResponse,
    UndoRequest,
    UndoResponse,
    UpdateBlockRequest,
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
        history: EditHistory | None = None,
    ) -> None:
        self.repository = repository
        self.engine = engine
        self.stay_duration = stay_duration
        self.recommender = recommender
        # 기본값은 로컬 Fake 저장소(FakeTripRepository)와 짝을 이루는 메모리 이력이다.
        # DB 저장소를 붙일 때 schedule_snapshots 를 쓰는 SnapshotRepository 구현으로 바꿔 주입해야 한다.
        self.history = history if history is not None else EditHistory(InMemorySnapshotRepository())
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

    def _accept(self, result: EngineResult) -> None:
        """저장 전 수락 검사: 고정 블록의 시각을 지킬 수 없는 결과는 거절한다."""
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

    def _save(self, trip_id: str, record: TripRecord, result: EngineResult) -> Schedule:
        self._accept(result)
        self.repository.save(trip_id, TripRecord(record.trip, result.state))
        return result.schedule

    def _commit_edit(self, trip_id: str, record: TripRecord, result: EngineResult) -> ScheduleMutationResponse:
        """편집 한 번을 확정한다: 수락 검사 → 편집 전 스냅샷 기록 → 저장.

        스냅샷은 수락 검사를 통과한 뒤에만 남기므로, 거절된 편집은 직전 EDIT 스냅샷을 바꾸지 않는다.
        상태가 그대로인 편집은 저장도 기록도 하지 않는다(되돌리기 1단계를 소비하지 않게).
        """
        if result.state != record.schedule:
            self._accept(result)
            self.history.record_before_edit(trip_id, record.schedule)
            self.repository.save(trip_id, TripRecord(record.trip, result.state))
        return ScheduleMutationResponse(schedule=result.schedule, violations=result.schedule.violations)

    def _run(self, command: RecomputeInput | ValidateInput, context: CalculationContext) -> EngineResult:
        if isinstance(command, RecomputeInput):
            return self.engine.recompute(command, context=context)
        return self.engine.project(command, context=context)

    def insert(self, trip_id: str, request: AddBlockRequest) -> ScheduleMutationResponse:
        with self._lock:
            record = self._get(trip_id)
            stay = self.stay_duration(request.place)
            if stay is None:
                raise PolicyRequiredError("Stay duration needs an agreed source")
            command = insert_command(request, record.trip, record.schedule, stay_min=stay)
            result = self.engine.insert(command, context=calculation_context(request))
            return self._commit_edit(trip_id, record, result)

    def update_block(self, trip_id: str, block_id: str, request: UpdateBlockRequest) -> ScheduleMutationResponse:
        with self._lock:
            record = self._get(trip_id)
            command = update_command(request, record.trip, record.schedule, block_id)
            return self._commit_edit(trip_id, record, self._run(command, calculation_context(request)))

    def delete_block(self, trip_id: str, block_id: str, request: DeleteBlockRequest) -> ScheduleMutationResponse:
        with self._lock:
            record = self._get(trip_id)
            command = delete_command(record.trip, record.schedule, block_id)
            return self._commit_edit(trip_id, record, self._run(command, calculation_context(request)))

    def undo(self, trip_id: str, request: UndoRequest) -> UndoResponse:
        """직전 편집 전 상태를 다시 계산하지 않고 그대로 저장한다. 되돌리기 자체는 스냅샷을 남기지 않는다."""
        with self._lock:
            record = self._get(trip_id)
            state = self.history.undo(trip_id)
            try:
                result = self.engine.project(
                    ValidateInput(trip=record.trip, schedule=state), context=calculation_context(request)
                )
            except Exception:
                # 응답을 만들지 못하면 소비한 스냅샷을 되살린다. DB 구현에서는 같은 트랜잭션의 롤백이다.
                self.history.record_before_edit(trip_id, state)
                raise
            self.repository.save(trip_id, TripRecord(record.trip, state))
            return UndoResponse(schedule=result.schedule)

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
