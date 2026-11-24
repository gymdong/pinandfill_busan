"""Trip facade for explicitly positioned edits and already anchored schedules."""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from threading import RLock

from app.modules.engine.initial import InitialSchedulePlanner
from app.modules.engine.interfaces import EngineResult, ItineraryEngine
from app.modules.engine.schemas import CalculationContext, RecomputeInput, ScheduleState, ValidateInput
from app.modules.engine.service import NeedsConfirmationError, PolicyRequiredError
from app.modules.recommend.waypoints import WaypointRecommender
from app.modules.trips.commands import calculation_context, delete_command, insert_command, update_command
from app.modules.trips.edit_history import EditHistory, InMemorySnapshotRepository, changed_block_ids
from app.modules.trips.initial import initial_command
from app.modules.trips.repository import TripRecord, TripRepository
from app.modules.trips.schemas import (
    AddBlockRequest,
    DeleteBlockRequest,
    GenerateScheduleRequest,
    GenerationMetadata,
    InitialScheduleResponse,
    InitialUnplaced,
    KakaoPlaceKey,
    PublicPlaceInput,
    Schedule,
    ScheduleMutationResponse,
    SuggestWaypointsRequest,
    SuggestWaypointsResponse,
    TripDates,
    TripDetail,
    TripDetailResponse,
    UndoRequest,
    UndoResponse,
    UpdateBlockRequest,
)

logger = logging.getLogger(__name__)


class TripNotFoundError(Exception):
    pass


class FixedScheduleConflictError(Exception):
    """Only request clientIds may be attached: request coordinates must never escape through errors.

    `client_ids` is filled by initial generation alone (request order); edit APIs leave it empty.
    """

    def __init__(self, client_ids: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.client_ids = client_ids


class StayDurationRequiredError(PolicyRequiredError):
    """요청 stayMin 도, 공공 장소 기본 체류시간도 없다. 화면이 체류시간을 입력받아 다시 보낸다."""


class InitialScheduleExistsError(PolicyRequiredError):
    """Initial generation cannot overwrite existing blocks or legs."""


class TripService:
    def __init__(
        self,
        repository: TripRepository,
        engine: ItineraryEngine,
        stay_duration: Callable[[PublicPlaceInput | KakaoPlaceKey], int | None],
        *,
        recommender: WaypointRecommender | None = None,
        history: EditHistory | None = None,
        initial_planner: InitialSchedulePlanner | None = None,
        transaction: Callable[[], AbstractContextManager[object]] = nullcontext,
    ) -> None:
        self.repository = repository
        self.engine = engine
        self.stay_duration = stay_duration
        self.recommender = recommender
        self.initial_planner = initial_planner
        # 기본값은 로컬 Fake 저장소(FakeTripRepository)와 짝을 이루는 메모리 이력이다.
        # DB 저장소를 붙일 때 schedule_snapshots 를 쓰는 SnapshotRepository 구현으로 바꿔 주입해야 한다.
        self.history = history if history is not None else EditHistory(InMemorySnapshotRepository())
        # Serializes edits of this local Fake service, including read/compute/save.
        # With DB repositories, `transaction` (Database.transaction) wraps each call: schedule and
        # history writes commit together or roll back together, and the trip row lock serializes workers.
        self._lock = RLock()
        self.transaction = transaction

    def suggest(self, trip_id: str, request: SuggestWaypointsRequest) -> SuggestWaypointsResponse:
        with self._lock, self.transaction():
            record = self._get(trip_id)
            if self.recommender is None:
                raise NeedsConfirmationError("Waypoint providers are not configured")
            return self.recommender.suggest(record, request, calculation_context(request))

    def detail(self, trip_id: str) -> TripDetailResponse:
        """API-026. 저장된 일정을 다시 계산하지 않고 투영한다(경로 조회 없음). GET 이라 카카오 좌표는 받지 않는다."""
        with self._lock, self.transaction():
            record = self._get(trip_id)
            result = self.engine.project(
                ValidateInput(trip=record.trip, schedule=record.schedule), context=CalculationContext()
            )
            trip = record.trip
            return TripDetailResponse(
                trip=TripDetail(
                    id=trip_id,
                    dates=TripDates(start=trip.start_date, end=trip.end_date),
                    day_start=trip.day_start,
                    day_end=trip.day_end,
                    mode=trip.transport_mode,
                ),
                schedule=result.schedule,
            )

    def _get(self, trip_id: str) -> TripRecord:
        record = self.repository.get(trip_id)
        if record is None:
            raise TripNotFoundError
        return record

    def _accept(self, result: EngineResult, *, days: set[int] | None = None) -> None:
        """저장 전 수락 검사: 고정 블록의 시각을 지킬 수 없는 결과는 거절한다.

        `days` 를 주면 그 날만 본다. 편집은 편집한 날만 보아, 다른 날에 이미 있던 충돌이 편집을 막지 않게 한다.
        """
        if self._timing_conflicts(result, days=days):
            raise FixedScheduleConflictError

    @staticmethod
    def _timing_conflicts(result: EngineResult, *, days: set[int] | None = None) -> set[str]:
        """고정 시각을 지킬 수 없는 고정 블록 ID."""
        timing_errors = {
            "TRAVEL_TIME_CONFLICT",
            "FIXED_TIME_CONFLICT",
            "STAY_CONFLICT",
            "DAY_WINDOW_CONFLICT",
            "TIME_WINDOW_UNSUPPORTED",
        }
        return {
            block.id
            for day in result.schedule.days
            if days is None or day.day_no in days
            for block in day.blocks
            if block.is_fixed and any(warning.type in timing_errors for warning in block.warnings)
        }

    def _commit_edit(self, trip_id: str, record: TripRecord, result: EngineResult) -> ScheduleMutationResponse:
        """편집 한 번을 확정한다: 수락 검사 → 편집 전 스냅샷 기록 → 저장.

        스냅샷은 수락 검사를 통과한 뒤에만 남기므로, 거절된 편집은 직전 EDIT 스냅샷을 바꾸지 않는다.
        저장이 실패하면 되돌리기 지점을 편집 전으로 정확히 되돌린다(DB 구현에서는 트랜잭션 롤백).
        상태가 그대로인 편집은 저장도 기록도 하지 않는다(되돌리기 1단계를 소비하지 않게).
        """
        if result.state != record.schedule:
            before = {block.id: block.day_no for block in record.schedule.blocks}
            after = {block.id: block.day_no for block in result.state.blocks}
            changed = changed_block_ids(record.schedule, result.state)
            # 편집은 한 날 안에서만 일어난다. 바뀐 블록이 있던 날·있는 날만 검사한다.
            self._accept(result, days={day_of[i] for day_of in (before, after) for i in changed if i in day_of})
            previous = self.history.latest_edit(trip_id)
            try:
                # 기록은 이전 지점을 지운 뒤 새 지점을 저장하므로, 기록 단계의 실패도 함께 되돌린다.
                self.history.record_before_edit(trip_id, record.schedule)
                self.repository.save(trip_id, TripRecord(record.trip, result.state))
            except Exception:
                self.history.restore(trip_id, previous)
                raise
        return ScheduleMutationResponse(schedule=result.schedule, violations=result.schedule.violations)

    def _run(self, command: RecomputeInput | ValidateInput, context: CalculationContext) -> EngineResult:
        if isinstance(command, RecomputeInput):
            return self.engine.recompute(command, context=context)
        return self.engine.project(command, context=context)

    def insert(self, trip_id: str, request: AddBlockRequest) -> ScheduleMutationResponse:
        with self._lock, self.transaction():
            record = self._get(trip_id)
            # 사용자 지정 → 공공 장소 값 순서. 둘 다 없으면 기본값을 만들지 않는다(#18 PM 결정 4).
            stay = request.stay_min if request.stay_min is not None else self.stay_duration(request.place)
            if stay is None:
                raise StayDurationRequiredError("Stay duration needs a user value or a public place value")
            command = insert_command(request, record.trip, record.schedule, stay_min=stay)
            result = self.engine.insert(command, context=calculation_context(request))
            return self._commit_edit(trip_id, record, result)

    def update_block(self, trip_id: str, block_id: str, request: UpdateBlockRequest) -> ScheduleMutationResponse:
        with self._lock, self.transaction():
            record = self._get(trip_id)
            command = update_command(request, record.trip, record.schedule, block_id)
            return self._commit_edit(trip_id, record, self._run(command, calculation_context(request)))

    def delete_block(self, trip_id: str, block_id: str, request: DeleteBlockRequest) -> ScheduleMutationResponse:
        with self._lock, self.transaction():
            record = self._get(trip_id)
            command = delete_command(record.trip, record.schedule, block_id)
            return self._commit_edit(trip_id, record, self._run(command, calculation_context(request)))

    def undo(self, trip_id: str, request: UndoRequest) -> UndoResponse:
        """직전 편집 전 상태를 다시 계산하지 않고 그대로 저장한다. 되돌리기 자체는 스냅샷을 남기지 않는다."""
        with self._lock, self.transaction():
            record = self._get(trip_id)
            snapshot = self.history.latest_edit(trip_id)
            state = self.history.undo(trip_id)
            try:
                result = self.engine.project(
                    ValidateInput(trip=record.trip, schedule=state), context=calculation_context(request)
                )
                self.repository.save(trip_id, TripRecord(record.trip, state))
            except Exception:
                # 응답을 만들거나 저장하지 못하면 소비한 스냅샷을 그대로 되살린다. DB 구현에서는 트랜잭션 롤백이다.
                self.history.restore(trip_id, snapshot)
                raise
            return UndoResponse(schedule=result.schedule)

    def _commit_generation(self, trip_id: str, record: TripRecord, result: EngineResult) -> None:
        """Reuse generation acceptance and EDIT compensation for both API-009 paths.

        This lock-scoped compensation is for the current memory repositories.
        Persistent repositories must commit schedule/history in one transaction.
        """
        self._accept(result)
        previous = self.history.latest_edit(trip_id)
        changed = result.state != record.schedule
        try:
            if changed:
                self.history.discard(trip_id)
            self.repository.save(trip_id, TripRecord(record.trip, result.state))
        except Exception:
            # Also compensate a provider that writes before reporting failure.
            # Schedule and history restores are guarded separately so either
            # failing never hides the original error or skips the other.
            try:
                if self.repository.get(trip_id) != record:
                    self.repository.save(trip_id, record)
            except Exception as restore_error:
                # Type only: repository errors may carry stored schedule data.
                logger.warning("trip_generation restore_failed error=%s", type(restore_error).__name__)
            if changed:
                try:
                    self.history.restore(trip_id, previous)
                except Exception as restore_error:
                    logger.warning("trip_generation history_restore_failed error=%s", type(restore_error).__name__)
            raise

    def _generate_initial(
        self, trip_id: str, record: TripRecord, request: GenerateScheduleRequest
    ) -> InitialScheduleResponse:
        if record.schedule.blocks or record.schedule.legs:
            raise InitialScheduleExistsError
        if self.initial_planner is None:
            raise NeedsConfirmationError("Initial schedule planner is not configured")
        assert request.initial is not None
        command, client_ids = initial_command(request.initial, record.trip)
        planned = self.initial_planner.plan(command, context=calculation_context(request))
        if planned.schedule is None:
            raise NeedsConfirmationError("Initial schedule presentation is unavailable")
        saved = not planned.unplaced
        if saved:
            result = EngineResult(planned.state, planned.schedule)
            # Includes global fixed-order conflicts, which have no block warning.
            conflicted = {block_id for conflict in planned.conflicts for block_id in conflict.block_ids}
            conflicted |= self._timing_conflicts(result)
            # A missing route is not a zero-minute route. Even without a route
            # estimate, a previous visit ending after the next fixed start is
            # already impossible; do not store that preview as a valid schedule.
            blocks = sorted(planned.state.blocks, key=lambda block: (block.day_no, block.seq))
            for previous, following in zip(blocks, blocks[1:], strict=False):
                if (
                    previous.day_no == following.day_no
                    and following.is_fixed
                    and previous.depart_at is not None
                    and following.fixed_start is not None
                    and previous.depart_at > following.fixed_start
                ):
                    conflicted |= {previous.id, following.id}
            if planned.conflicts or conflicted:
                # Request-local mapping only, in request order; server UUIDs never leave as error data.
                raise FixedScheduleConflictError(tuple(cid for bid, cid in client_ids.items() if bid in conflicted))
            self._commit_generation(trip_id, record, result)
        return InitialScheduleResponse(
            days=planned.schedule.days,
            violations=planned.schedule.violations,
            conflicts=planned.schedule.conflicts,
            generation=GenerationMetadata(
                saved=saved,
                confirmed=planned.confirmed,
                unplaced=tuple(
                    InitialUnplaced(client_id=client_ids[item.block_id], reason=item.reason)
                    for item in planned.unplaced
                ),
                preview_client_ids={} if saved else {block.id: client_ids[block.id] for block in planned.state.blocks},
            ),
        )

    def generate(self, trip_id: str, request: GenerateScheduleRequest) -> Schedule | InitialScheduleResponse:
        with self._lock, self.transaction():
            record = self._get(trip_id)
            if request.initial is not None:
                return self._generate_initial(trip_id, record, request)
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
            self._commit_generation(trip_id, record, result)
            return result.schedule
