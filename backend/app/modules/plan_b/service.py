"""FR-010 플랜 B: 다음 블록이 붐빌 때 강행 / 순서 바꾸기 / 대체 장소 3안을 계산한다(SD-04, UC-007).

- 조회(API-014)는 아무것도 저장하지 않는다. 사용자가 고르기 전에는 일정을 바꾸지 않는다(원칙 5).
- 적용(API-015)은 고른 안을 지금 일정 위에서 다시 계산해 엔진 결과를 돌려준다. 저장·되돌리기 기록은 TripService 가 한다.
- 고정 블록은 대상이 아니다. 순서를 바꾸거나 다른 장소로 바꾸면 사용자가 정한 장소·시각이 움직인다(원칙 1).
  다른 블록을 바꾼 결과가 고정 블록의 시각을 지킬 수 없으면 그 안은 내지 않는다.
- 덜 붐빈다는 판단은 혼잡 신뢰도가 기준(기본 '중간') 이상일 때만 한다. 혼잡을 모르는 대체 장소는 '정보 부족'으로 보인다.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import uuid4

from app.adapters.route.estimated import distance_km
from app.modules.crowd.avoidance import meets_confidence, window_cost
from app.modules.crowd.schemas import CrowdConfidence, PlaceCrowdResponse
from app.modules.engine.interfaces import CrowdLookup, EngineResult, ItineraryEngine, PlaceDataProvider
from app.modules.engine.schemas import (
    CalculationContext,
    PublicPlaceRef,
    RecomputeInput,
    ScheduleState,
    StoredBlock,
    ValidateInput,
)
from app.modules.engine.service import EngineInputError, NeedsConfirmationError, PolicyRequiredError
from app.modules.plan_b.schemas import PlanBOption, PlanBResponse, PlanBTrigger
from app.modules.recommend.waypoints import CandidateProvider, crowd_at_stay
from app.modules.trips.acceptance import fixed_timing_conflicts
from app.modules.trips.commands import replace_command, update_command
from app.modules.trips.repository import TripRecord
from app.modules.trips.schemas import Block, CrowdSummary, PlaceSummary, UpdateBlockRequest

TRIGGER_GRADES = frozenset({"붐빔", "매우 붐빔"})
# 영업시간과 맞지 않는 경고. HOURS_NEEDS_CHECK(영업시간 모름)는 충돌이 아니라 확인 필요다.
HOURS_CONFLICTS = frozenset({"CLOSED_DAY", "TIME_WINDOW_CONFLICT"})
# 대체 장소 자신에게 있어도 되는 경고(확인 필요·경로 시각 의미). 나머지가 있으면 그 장소는 내지 않는다.
REPLACEMENT_ALLOWED_WARNINGS = frozenset({"HOURS_NEEDS_CHECK", "ROUTE_TIME_CONTEXT_ONLY"})

KEEP_ID = "KEEP"


@dataclass(frozen=True, slots=True)
class _Evaluated:
    option_id: str
    result: EngineResult
    block: Block
    cost: float | None
    crowd: CrowdSummary | None
    extra: int | None
    hours_conflict: bool


def _day_travel(state: ScheduleState, day_no: int) -> int | None:
    """그 날 블록 사이 구간 이동시간 합. 이웃 구간 중 하나라도 시간을 모르면 None."""
    blocks = sorted((b for b in state.blocks if b.day_no == day_no), key=lambda b: b.seq)
    legs = {(leg.from_block_id, leg.to_block_id): leg for leg in state.legs}
    total = 0
    for before, after in zip(blocks, blocks[1:], strict=False):
        leg = legs.get((before.id, after.id))
        if leg is None or leg.duration_min is None:
            return None
        total += leg.duration_min
    return total


def _day_blocks(result: EngineResult, day_no: int) -> list[Block]:
    return [block for day in result.schedule.days if day.day_no == day_no for block in day.blocks]


class PlanBPlanner:
    def __init__(
        self,
        engine: ItineraryEngine,
        places: PlaceDataProvider,
        candidates: CandidateProvider,
        *,
        crowd: CrowdLookup | None,
        min_confidence: CrowdConfidence = "중간",
        min_gain: float = 0.1,
        max_positions: int = 4,
        max_replacements: int = 6,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self.engine = engine
        self.places = places
        self.candidates = candidates
        self.crowd = crowd
        self.min_confidence = min_confidence
        # 지금보다 체류 구간 평균 score 가 이만큼 낮아야 '덜 붐빈다'고 본다(FR-009 회피와 같은 기준).
        self.min_gain = min_gain
        # 경로 조회 예산 보호: 순서 바꾸기로 다시 계산해 볼 위치 수와 대체 장소 후보 수.
        self.max_positions = max_positions
        self.max_replacements = max_replacements
        self.id_factory = id_factory

    # ---------- 조회(API-014) ----------

    def options(self, record: TripRecord, block_id: str, context: CalculationContext) -> PlanBResponse:
        block = self._block(record, block_id)
        day = record.trip.start_date + timedelta(days=block.day_no - 1)
        crowd = self._lookup(block, day)
        summary = self._summary(crowd, block)
        trigger = self._trigger(block, crowd, summary)
        if trigger is None:
            return PlanBResponse(block_id=block_id, trigger=None, crowd=summary)
        base = self.engine.project(ValidateInput(trip=record.trip, schedule=record.schedule), context=context)
        base_travel = _day_travel(record.schedule, block.day_no)
        base_cost = (
            window_cost(crowd, block.arrive_at, block.depart_at)
            if crowd is not None and block.arrive_at is not None and block.depart_at is not None
            else None
        )
        keep = PlanBOption(
            id=KEEP_ID,
            kind="KEEP",
            available=True,
            extra_minutes=0,
            hours_conflict=self._hours_conflict(_day_blocks(base, block.day_no)),
            arrive_at=block.arrive_at,
            depart_at=block.depart_at,
            crowd=summary,
        )
        return PlanBResponse(
            block_id=block_id,
            trigger=trigger,
            crowd=summary,
            options=(
                keep,
                self._reorder_option(record, block, crowd, base_cost, base_travel, context),
                self._replace_option(record, block, day, base_cost, base_travel, context),
            ),
        )

    def _trigger(
        self, block: StoredBlock, crowd: PlaceCrowdResponse | None, summary: CrowdSummary | None
    ) -> PlanBTrigger | None:
        if block.is_fixed or block.arrive_at is None or summary is None:
            return None
        if summary.grade in TRIGGER_GRADES and meets_confidence(crowd, self.min_confidence):
            return "CROWD"
        return None

    def _reorder_option(
        self,
        record: TripRecord,
        block: StoredBlock,
        crowd: PlaceCrowdResponse | None,
        base_cost: float | None,
        base_travel: int | None,
        context: CalculationContext,
    ) -> PlanBOption:
        best: _Evaluated | None = None
        if crowd is not None and base_cost is not None:
            for seq in self._positions(record.schedule, block):
                option_id = f"REORDER:{block.id}:{seq}"
                evaluated = self._evaluate(record, option_id, block.id, block.day_no, crowd, base_travel, context)
                if evaluated is None or evaluated.cost is None or base_cost - evaluated.cost < self.min_gain - 1e-9:
                    continue
                if best is None or (evaluated.cost, evaluated.extra or 0) < (best.cost or 0, best.extra or 0):
                    best = evaluated
        if best is None:
            return PlanBOption(
                id=f"REORDER:{block.id}",
                kind="REORDER",
                available=False,
                extra_minutes=None,
                hours_conflict=False,
                note="고정 시각을 지키면서 덜 붐비게 되는 순서가 없어요.",
            )
        return self._option(best, "REORDER")

    def _replace_option(
        self,
        record: TripRecord,
        block: StoredBlock,
        day: date,
        base_cost: float | None,
        base_travel: int | None,
        context: CalculationContext,
    ) -> PlanBOption:
        ranked: list[tuple[tuple[int, float, int, str], _Evaluated]] = []
        for candidate_id in self._replacement_ids(record, block, day):
            option_id = f"REPLACE:{block.id}:{candidate_id}"
            evaluated = self._evaluate(record, option_id, None, block.day_no, None, base_travel, context)
            if evaluated is None:
                continue
            known = evaluated.cost is not None and evaluated.crowd is not None
            if known and base_cost is not None and base_cost - (evaluated.cost or 0) < self.min_gain - 1e-9:
                # 혼잡을 아는데 덜 붐비지 않으면 대체 장소로 내지 않는다.
                continue
            key = (0 if known else 1, evaluated.cost or 0.0, evaluated.extra or 0, candidate_id)
            ranked.append((key, evaluated))
        if not ranked:
            return PlanBOption(
                id=f"REPLACE:{block.id}",
                kind="REPLACE",
                available=False,
                extra_minutes=None,
                hours_conflict=False,
                note="근처에 덜 붐비는 대체 장소가 없어요.",
            )
        ranked.sort(key=lambda row: row[0])
        return self._option(ranked[0][1], "REPLACE")

    def _option(self, evaluated: _Evaluated, kind: str) -> PlanBOption:
        place = evaluated.block.place if isinstance(evaluated.block.place, PlaceSummary) else None
        return PlanBOption(
            id=evaluated.option_id,
            kind="REORDER" if kind == "REORDER" else "REPLACE",
            available=True,
            extra_minutes=evaluated.extra,
            hours_conflict=evaluated.hours_conflict,
            arrive_at=evaluated.block.arrive_at,
            depart_at=evaluated.block.depart_at,
            crowd=evaluated.crowd,
            place=place if kind == "REPLACE" else None,
        )

    def _evaluate(
        self,
        record: TripRecord,
        option_id: str,
        target_id: str | None,
        day_no: int,
        crowd: PlaceCrowdResponse | None,
        base_travel: int | None,
        context: CalculationContext,
    ) -> _Evaluated | None:
        """한 안을 계산한다. 고정 시각을 못 지키거나 계산할 수 없으면 None."""
        try:
            result, new_id = self._compute(record, option_id, context)
        except (EngineInputError, PolicyRequiredError, NeedsConfirmationError):
            return None
        if fixed_timing_conflicts(result, days={day_no}):
            return None
        target = next((b for b in _day_blocks(result, day_no) if b.id == (target_id or new_id)), None)
        if target is None or target.arrive_at is None or target.depart_at is None:
            return None
        if target_id is None:
            # 대체 장소: 공공 장소이고, 자신에게 영업시간 충돌 등 확인할 수 없는 경고가 없어야 한다.
            if not isinstance(target.place, PlaceSummary):
                return None
            if any(w.type not in REPLACEMENT_ALLOWED_WARNINGS for w in target.warnings):
                return None
            stored = next(b for b in result.state.blocks if b.id == new_id)
            crowd = self._lookup(stored, record.trip.start_date + timedelta(days=day_no - 1))
        summary, cost = crowd_at_stay(crowd, target.arrive_at, target.depart_at, self.min_confidence)
        travel = _day_travel(result.state, day_no)
        return _Evaluated(
            option_id=option_id,
            result=result,
            block=target,
            cost=cost,
            crowd=summary,
            extra=None if travel is None or base_travel is None else travel - base_travel,
            hours_conflict=self._hours_conflict(_day_blocks(result, day_no)),
        )

    def _positions(self, schedule: ScheduleState, block: StoredBlock) -> list[int]:
        """같은 날 다른 자리(seq). 지금 자리에서 가까운 순으로 `max_positions` 개."""
        size = sum(1 for b in schedule.blocks if b.day_no == block.day_no)
        seqs = [seq for seq in range(1, size + 1) if seq != block.seq]
        seqs.sort(key=lambda seq: (abs(seq - block.seq), seq))
        return seqs[: self.max_positions]

    def _replacement_ids(self, record: TripRecord, block: StoredBlock, day: date) -> list[str]:
        """일정에 없는 공공 장소 중 대상 장소에서 직선거리가 가까운 `max_replacements` 곳."""
        origin = self.places.get(block.place_ref, on_date=day) if isinstance(block.place_ref, PublicPlaceRef) else None
        if origin is None or origin.lat is None or origin.lng is None:
            return []
        in_trip = {b.place_ref for b in record.schedule.blocks}
        scored: list[tuple[float, str]] = []
        for candidate in self.candidates.candidates(on_date=day):
            if candidate.ref in in_trip or candidate.stay_min is None:
                continue
            distance = distance_km(origin, self.places.get(candidate.ref, on_date=day))
            if distance is not None:
                scored.append((distance, candidate.ref.place_id))
        scored.sort()
        return [place_id for _, place_id in scored[: self.max_replacements]]

    # ---------- 적용(API-015) ----------

    def apply(self, record: TripRecord, option_id: str, context: CalculationContext) -> EngineResult:
        """고른 안을 지금 일정 위에서 다시 계산한다. KEEP 은 TripService 가 저장 없이 처리한다."""
        result, _ = self._compute(record, option_id, context)
        return result

    def _compute(self, record: TripRecord, option_id: str, context: CalculationContext) -> tuple[EngineResult, str]:
        kind, _, rest = option_id.partition(":")
        block_id, _, argument = rest.partition(":")
        if kind not in {"REORDER", "REPLACE"} or not block_id or not argument:
            raise EngineInputError("Unknown plan B option")
        block = self._block(record, block_id)
        if block.is_fixed:
            raise EngineInputError("Fixed blocks have no plan B")
        if kind == "REORDER":
            if not argument.isdigit():
                raise EngineInputError("Unknown plan B option")
            command = update_command(UpdateBlockRequest(seq=int(argument)), record.trip, record.schedule, block_id)
            return self._run(command, context), block_id
        day = record.trip.start_date + timedelta(days=block.day_no - 1)
        ref = PublicPlaceRef(place_id=argument)
        offered = {c.ref.place_id: c for c in self.candidates.candidates(on_date=day)}
        candidate = offered.get(argument)
        if candidate is None or candidate.stay_min is None or ref in {b.place_ref for b in record.schedule.blocks}:
            raise EngineInputError("Replacement is not available")
        new_id = self.id_factory()
        command = replace_command(
            record.trip, record.schedule, block_id, place_ref=ref, stay_min=candidate.stay_min, new_block_id=new_id
        )
        return self._run(command, context), new_id

    # ---------- 공통 ----------

    def _run(self, command: RecomputeInput | ValidateInput, context: CalculationContext) -> EngineResult:
        if isinstance(command, RecomputeInput):
            return self.engine.recompute(command, context=context)
        return self.engine.project(command, context=context)

    @staticmethod
    def _block(record: TripRecord, block_id: str) -> StoredBlock:
        block = next((b for b in record.schedule.blocks if b.id == block_id), None)
        if block is None:
            raise EngineInputError("Block does not exist")
        return block

    def _lookup(self, block: StoredBlock, day: date) -> PlaceCrowdResponse | None:
        if self.crowd is None or not isinstance(block.place_ref, PublicPlaceRef):
            return None
        try:
            return self.crowd.crowd(block.place_ref, on_date=day)
        except Exception:
            # 혼잡 조회 실패는 '정보 부족'과 같다. 플랜 B 때문에 일정 화면이 실패하지 않게 한다.
            return None

    def _summary(self, crowd: PlaceCrowdResponse | None, block: StoredBlock) -> CrowdSummary | None:
        if block.arrive_at is None or block.depart_at is None:
            return None
        summary, _ = crowd_at_stay(crowd, block.arrive_at, block.depart_at, self.min_confidence)
        return summary

    @staticmethod
    def _hours_conflict(blocks: list[Block]) -> bool:
        return any(w.type in HOURS_CONFLICTS for b in blocks for w in b.warnings)
