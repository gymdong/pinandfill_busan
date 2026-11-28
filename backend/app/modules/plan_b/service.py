"""FR-010 플랜 B: 다음 블록이 붐빌 때 강행 / 순서 바꾸기 / 대체 장소 3안을 계산한다(SD-04, UC-007).

- 조회(API-014)는 아무것도 저장하지 않는다. 사용자가 고르기 전에는 일정을 바꾸지 않는다(원칙 5).
  조회는 `preview_engine`(기본 구성은 직선거리 추정만 쓰는 엔진)으로 계산해 경로 API 를 부르지 않는다.
  그래서 안의 이동시간은 '추정'이다(`estimated`). 실제 경로 조회는 적용 때만 한다(TMAP 일일 한도 보호).
- 적용(API-015)은 지금 일정으로 3안을 다시 계산해 고른 안이 아직 그대로 유효할 때만 실제 엔진으로 계산한다.
  그 사이 일정이 바뀌어 안이 사라졌거나 더 이상 덜 붐비지 않으면 `PlanBStaleError` 다.
  저장·되돌리기 기록은 TripService 가 한다.
- 고정 블록은 대상이 아니다. 순서를 바꾸거나 다른 장소로 바꾸면 사용자가 정한 장소·시각이 움직인다(원칙 1).
  안을 적용했을 때 원래 없던 시각 충돌(고정 시각·하루 범위·이동시간·체류)이 생기면 그 안은 내지 않는다.
- 덜 붐빈다는 판단은 혼잡 신뢰도가 기준(기본 '중간') 이상일 때만 한다. 혼잡을 모르는 대체 장소는 '정보 부족'으로 보이고,
  근거가 약해도 '붐빔' 이상으로 보이는 장소는 대체 장소로 내지 않는다.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal, Protocol
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
from app.modules.plan_b.schemas import PlanBKind, PlanBOption, PlanBResponse, PlanBTrigger
from app.modules.recommend.waypoints import CandidateProvider, crowd_at_stay
from app.modules.trips.acceptance import FIXED_TIMING_ERRORS
from app.modules.trips.commands import replace_command, update_command
from app.modules.trips.repository import TripRecord
from app.modules.trips.schemas import Block, CrowdSummary, PlaceSummary, UpdateBlockRequest

TRIGGER_GRADES = frozenset({"붐빔", "매우 붐빔"})
GRADE_RANK = {"여유": 0, "보통": 1, "붐빔": 2, "매우 붐빔": 3}
# 영업시간과 맞지 않는 경고. HOURS_NEEDS_CHECK(영업시간 모름)는 충돌이 아니라 확인 필요다.
HOURS_CONFLICTS = frozenset({"CLOSED_DAY", "TIME_WINDOW_CONFLICT"})
# 안을 적용해 원래 없던 이 경고가 그 날 어느 블록에든 생기면 그 안은 내지 않는다.
TIMING_CONFLICTS = FIXED_TIMING_ERRORS | {"DAY_OVERFLOW"}
# 대체 장소 자신에게 있어도 되는 경고(확인 필요·경로 시각 의미). 나머지가 있으면 그 장소는 내지 않는다.
REPLACEMENT_ALLOWED_WARNINGS = frozenset({"HOURS_NEEDS_CHECK", "ROUTE_TIME_CONTEXT_ONLY"})
SEQ_PATTERN = re.compile(r"[1-9][0-9]{0,3}")

KEEP_ID = "KEEP"

# 안을 내지 못한 이유. 화면 문구(note)를 고른다.
Reason = Literal["UNKNOWN_TIME", "CONFLICT", "ENGINE", "UNSUITABLE", "NO_GAIN"]
NOTES: dict[PlanBKind, dict[str, str]] = {
    "REORDER": {
        "UNKNOWN_TIME": "이동시간을 몰라 다른 순서를 계산할 수 없어요.",
        "ENGINE": "지금은 다른 순서를 계산할 수 없어요.",
        "DEFAULT": "고정 시각과 하루 일정을 지키면서 덜 붐비게 되는 순서가 없어요.",
    },
    "REPLACE": {
        "UNKNOWN_TIME": "이동시간을 몰라 대체 장소를 계산할 수 없어요.",
        "ENGINE": "지금은 대체 장소를 계산할 수 없어요.",
        "DEFAULT": "근처에 덜 붐비는 대체 장소가 없어요.",
    },
}


class RainLookup(Protocol):
    """시간 단위 비 예보(FR-013). 단기예보가 없으면 None(판단하지 않는다)."""

    def rain(self, lat: float, lng: float, day: date, hour: int) -> bool | None: ...


RAIN_NOTES: dict[PlanBKind, str] = {
    "REORDER": "비 예보를 피하면서 고정 시각과 하루 일정을 지키는 순서가 없어요.",
    "REPLACE": "근처에 비를 피할 실내 대체 장소가 없어요.",
}


class PlanBStaleError(Exception):
    """고른 안이 지금 일정에서는 없거나 달라졌다. 화면이 3안을 다시 불러야 한다."""


class PlanBRouteConflictError(Exception):
    """추정으로는 되던 안이 실제 경로로 계산하니 하루 범위·고정 시각 등을 지킬 수 없다. 그 안만 고를 수 없다."""


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


def _timing_flags(result: EngineResult, day_no: int, rename: dict[str, str] | None = None) -> set[tuple[str, str]]:
    """그 날 (블록 ID, 시각 충돌 경고) 쌍. `rename` 은 대체 장소의 새 ID 를 원래 블록 ID 로 본다."""
    names = rename or {}
    return {
        (names.get(block.id, block.id), warning.type)
        for block in _day_blocks(result, day_no)
        for warning in block.warnings
        if warning.type in TIMING_CONFLICTS
    }


class PlanBPlanner:
    def __init__(
        self,
        engine: ItineraryEngine,
        places: PlaceDataProvider,
        candidates: CandidateProvider,
        *,
        crowd: CrowdLookup | None,
        preview_engine: ItineraryEngine | None = None,
        min_confidence: CrowdConfidence = "중간",
        min_gain: float = 0.1,
        max_positions: int = 4,
        max_replacements: int = 6,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
        rain: RainLookup | None = None,
        outdoor: Callable[[str], bool | None] | None = None,
    ) -> None:
        self.engine = engine
        # 조회용 엔진. 주지 않으면 적용과 같은 엔진이다(시험용 가짜 경로 등).
        self.preview_engine = preview_engine if preview_engine is not None else engine
        self.places = places
        self.candidates = candidates
        self.crowd = crowd
        self.min_confidence = min_confidence
        # 지금보다 체류 구간 평균 score 가 이만큼 낮아야 '덜 붐빈다'고 본다(FR-009 회피와 같은 기준).
        self.min_gain = min_gain
        # 계산 예산 보호: 순서 바꾸기로 다시 계산해 볼 위치 수와 대체 장소 후보 수.
        self.max_positions = max_positions
        self.max_replacements = max_replacements
        self.id_factory = id_factory
        # 비 예보 트리거(FR-010·013): 실외 장소(outdoor)의 도착 시각에 시간 단위 비 예보가 있으면 띄운다.
        self.rain_lookup = rain
        self.outdoor = outdoor

    # ---------- 조회(API-014) ----------

    def options(self, record: TripRecord, block_id: str, context: CalculationContext) -> PlanBResponse:
        block = self._block(record, block_id)
        day = record.trip.start_date + timedelta(days=block.day_no - 1)
        crowd = self._lookup(block, day)
        summary = self._summary(crowd, block)
        trigger = self._trigger(block, crowd, summary, day)
        if trigger is None:
            return PlanBResponse(block_id=block_id, trigger=None, crowd=summary)
        engine = self.preview_engine
        # 비교 기준(지금 일정)도 안과 같은 엔진으로 그 날 처음부터 다시 계산한다. 저장된 실제 경로값과
        # 추정값을 섞어 비교하면 이동시간 차이·충돌 판단·덜 붐빔 판단이 틀린다.
        base = self._baseline(record, block.day_no, context, engine)
        base_flags = _timing_flags(base, block.day_no)
        base_travel = _day_travel(base.state, block.day_no)
        base_block = next((b for b in base.state.blocks if b.id == block.id), block)
        base_cost = (
            window_cost(crowd, base_block.arrive_at, base_block.depart_at)
            if crowd is not None and base_block.arrive_at is not None and base_block.depart_at is not None
            else None
        )
        stored = self.engine.project(ValidateInput(trip=record.trip, schedule=record.schedule), context=context)
        keep = PlanBOption(
            id=KEEP_ID,
            kind="KEEP",
            available=True,
            extra_minutes=0,
            hours_conflict=self._hours_conflict(_day_blocks(stored, block.day_no)),
            arrive_at=block.arrive_at,
            depart_at=block.depart_at,
            crowd=summary,
        )
        evaluate = _Evaluator(self, record, block, base_flags, base_travel, context, engine)
        return PlanBResponse(
            block_id=block_id,
            trigger=trigger,
            crowd=summary,
            estimated=engine is not self.engine,
            options=(
                (
                    keep,
                    self._rain_reorder(record, block, day, evaluate),
                    self._rain_replace(record, block, day, evaluate),
                )
                if trigger == "RAIN"
                else (
                    keep,
                    self._reorder_option(record, block, crowd, base_cost, evaluate),
                    self._replace_option(record, block, day, summary, base_cost, evaluate),
                )
            ),
        )

    def _baseline(
        self, record: TripRecord, day_no: int, context: CalculationContext, engine: ItineraryEngine
    ) -> EngineResult:
        """지금 일정을 `engine` 으로 그 날 첫 블록부터 다시 계산한 결과. 계산할 수 없으면 저장된 일정 투영."""
        if engine is self.engine:
            return engine.project(ValidateInput(trip=record.trip, schedule=record.schedule), context=context)
        first = min((b for b in record.schedule.blocks if b.day_no == day_no), key=lambda b: b.seq)
        try:
            return engine.recompute(
                RecomputeInput(trip=record.trip, schedule=record.schedule, from_block_id=first.id), context=context
            )
        except (EngineInputError, PolicyRequiredError, NeedsConfirmationError):
            return engine.project(ValidateInput(trip=record.trip, schedule=record.schedule), context=context)

    def _trigger(
        self, block: StoredBlock, crowd: PlaceCrowdResponse | None, summary: CrowdSummary | None, day: date
    ) -> PlanBTrigger | None:
        if block.is_fixed or block.arrive_at is None:
            return None
        # 비 예보가 혼잡보다 먼저다(실외에서 비를 맞는 쪽이 더 큰 문제다).
        if self._is_outdoor(block.place_ref) and self._raining(block.place_ref, day, block.arrive_at.hour):
            return "RAIN"
        if summary is None:
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
        evaluate: "_Evaluator",
    ) -> PlanBOption:
        ranked: list[tuple[tuple[bool, float, int], _Evaluated]] = []
        reasons: set[str] = set()
        if crowd is None or base_cost is None:
            reasons.add("NO_GAIN")
        else:
            for seq in self._positions(record.schedule, block):
                evaluated = evaluate(f"REORDER:{block.id}:{seq}", crowd)
                if isinstance(evaluated, str):
                    reasons.add(evaluated)
                    continue
                if evaluated.cost is None or base_cost - evaluated.cost < self.min_gain - 1e-9:
                    reasons.add("NO_GAIN")
                    continue
                # 영업시간 충돌이 없는 안 → 덜 붐비는 안 → 이동이 덜 느는 안.
                ranked.append(((evaluated.hours_conflict, evaluated.cost, evaluated.extra or 0), evaluated))
        if not ranked:
            return self._unavailable("REORDER", block.id, reasons)
        ranked.sort(key=lambda row: row[0])
        return self._option(ranked[0][1], "REORDER")

    def _replace_option(
        self,
        record: TripRecord,
        block: StoredBlock,
        day: date,
        summary: CrowdSummary | None,
        base_cost: float | None,
        evaluate: "_Evaluator",
    ) -> PlanBOption:
        ranked: list[tuple[tuple[int, bool, float, int, str], _Evaluated]] = []
        reasons: set[str] = set()
        base_rank = GRADE_RANK.get(summary.grade or "", 3) if summary is not None else 3
        for candidate_id in self._replacement_ids(record, block, day):
            evaluated = evaluate(f"REPLACE:{block.id}:{candidate_id}", None)
            if isinstance(evaluated, str):
                reasons.add(evaluated)
                continue
            grade = evaluated.crowd.grade if evaluated.crowd is not None else None
            if grade in TRIGGER_GRADES:
                # 근거가 약해도 붐빈다고 보이는 곳은 '덜 붐비는 대체 장소'가 아니다.
                reasons.add("NO_GAIN")
                continue
            if evaluated.cost is not None:
                gain_ok = (
                    base_cost - evaluated.cost >= self.min_gain - 1e-9
                    if base_cost is not None
                    else GRADE_RANK.get(grade or "", 3) < base_rank
                )
                if not gain_ok:
                    reasons.add("NO_GAIN")
                    continue
            # 신뢰할 만한 근거로 덜 붐비는 곳 → 근거가 약하거나 정보 부족인 곳 순.
            rank = 0 if evaluated.cost is not None else 1
            key = (rank, evaluated.hours_conflict, evaluated.cost or 0.0, evaluated.extra or 0, candidate_id)
            ranked.append((key, evaluated))
        if not ranked:
            return self._unavailable("REPLACE", block.id, reasons)
        ranked.sort(key=lambda row: row[0])
        return self._option(ranked[0][1], "REPLACE")

    # ---------- 비 예보(RAIN) ----------

    def _is_outdoor(self, ref: object) -> bool:
        return isinstance(ref, PublicPlaceRef) and self.outdoor is not None and self.outdoor(ref.place_id) is True

    def _raining(self, ref: object, day: date, hour: int) -> bool:
        """그 장소·시각의 시간 단위 비 예보. 모르면 False(비를 근거로 바꾸지 않는다)."""
        if self.rain_lookup is None or not isinstance(ref, PublicPlaceRef):
            return False
        place = self.places.get(ref, on_date=day)
        if place.lat is None or place.lng is None:
            return False
        return self.rain_lookup.rain(place.lat, place.lng, day, hour) is True

    def _dry(self, ref: object, day: date, hour: int) -> bool:
        """비 예보가 없다고 확인되는가(단기예보로 비가 아님)."""
        if self.rain_lookup is None or not isinstance(ref, PublicPlaceRef):
            return False
        place = self.places.get(ref, on_date=day)
        if place.lat is None or place.lng is None:
            return False
        return self.rain_lookup.rain(place.lat, place.lng, day, hour) is False

    def _rain_reorder(self, record: TripRecord, block: StoredBlock, day: date, evaluate: "_Evaluator") -> PlanBOption:
        ranked: list[tuple[tuple[bool, int], _Evaluated]] = []
        reasons: set[str] = set()
        for seq in self._positions(record.schedule, block):
            evaluated = evaluate(f"REORDER:{block.id}:{seq}", None)
            if isinstance(evaluated, str):
                reasons.add(evaluated)
                continue
            arrive = evaluated.block.arrive_at
            if arrive is None or not self._dry(block.place_ref, day, arrive.hour):
                reasons.add("NO_GAIN")
                continue
            ranked.append(((evaluated.hours_conflict, evaluated.extra or 0), evaluated))
        if not ranked:
            option = self._unavailable("REORDER", block.id, reasons)
            return (
                option
                if option.note != NOTES["REORDER"]["DEFAULT"]
                else option.model_copy(update={"note": RAIN_NOTES["REORDER"]})
            )
        ranked.sort(key=lambda row: row[0])
        return self._option(ranked[0][1], "REORDER")

    def _rain_replace(self, record: TripRecord, block: StoredBlock, day: date, evaluate: "_Evaluator") -> PlanBOption:
        ranked: list[tuple[tuple[int, bool, int, str], _Evaluated]] = []
        reasons: set[str] = set()
        for candidate_id in self._replacement_ids(record, block, day):
            evaluated = evaluate(f"REPLACE:{block.id}:{candidate_id}", None)
            if isinstance(evaluated, str):
                reasons.add(evaluated)
                continue
            grade = evaluated.crowd.grade if evaluated.crowd is not None else None
            ref = PublicPlaceRef(place_id=candidate_id)
            indoor = self.outdoor is not None and self.outdoor(candidate_id) is False
            arrive = evaluated.block.arrive_at
            dry = arrive is not None and self._dry(ref, day, arrive.hour)
            if grade in TRIGGER_GRADES or not (indoor or dry):
                reasons.add("NO_GAIN")
                continue
            # 실내 장소 → 비가 그친 실외 장소 순, 그다음 영업시간 충돌·이동시간.
            ranked.append(
                ((0 if indoor else 1, evaluated.hours_conflict, evaluated.extra or 0, candidate_id), evaluated)
            )
        if not ranked:
            option = self._unavailable("REPLACE", block.id, reasons)
            return (
                option
                if option.note != NOTES["REPLACE"]["DEFAULT"]
                else option.model_copy(update={"note": RAIN_NOTES["REPLACE"]})
            )
        ranked.sort(key=lambda row: row[0])
        return self._option(ranked[0][1], "REPLACE")

    @staticmethod
    def _unavailable(kind: PlanBKind, block_id: str, reasons: set[str]) -> PlanBOption:
        notes = NOTES[kind]
        if "UNKNOWN_TIME" in reasons and not reasons & {"NO_GAIN", "CONFLICT"}:
            note = notes["UNKNOWN_TIME"]
        elif reasons == {"ENGINE"}:
            note = notes["ENGINE"]
        else:
            note = notes["DEFAULT"]
        return PlanBOption(
            id=f"{kind}:{block_id}", kind=kind, available=False, extra_minutes=None, hours_conflict=False, note=note
        )

    @staticmethod
    def _option(evaluated: _Evaluated, kind: PlanBKind) -> PlanBOption:
        place = evaluated.block.place if isinstance(evaluated.block.place, PlaceSummary) else None
        return PlanBOption(
            id=evaluated.option_id,
            kind=kind,
            available=True,
            extra_minutes=evaluated.extra,
            hours_conflict=evaluated.hours_conflict,
            arrive_at=evaluated.block.arrive_at,
            depart_at=evaluated.block.depart_at,
            crowd=evaluated.crowd,
            place=place if kind == "REPLACE" else None,
        )

    def _positions(self, schedule: ScheduleState, block: StoredBlock) -> list[int]:
        """같은 날 다른 자리(seq). 지금 자리에서 가까운 순으로 `max_positions` 개."""
        size = sum(1 for b in schedule.blocks if b.day_no == block.day_no)
        seqs = [seq for seq in range(1, size + 1) if seq != block.seq]
        seqs.sort(key=lambda seq: (abs(seq - block.seq), seq))
        return seqs[: self.max_positions]

    def _replacement_ids(self, record: TripRecord, block: StoredBlock, day: date) -> list[str]:
        """일정에 없는 공공 장소 중 대상 장소에서 직선거리가 가까운 `max_replacements` 곳."""
        if not isinstance(block.place_ref, PublicPlaceRef):
            return []
        origin = self.places.get(block.place_ref, on_date=day)
        if origin.lat is None or origin.lng is None:
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
        """고른 안을 지금 일정으로 다시 확인한 뒤 실제 엔진으로 계산한다. KEEP 은 TripService 가 저장 없이 처리한다.

        지금 일정에서 그 안이 없거나(다른 편집으로 바뀜) 고를 수 없으면, 또는 실제 경로로 계산하니 원래 없던
        시각 충돌이 생기면 `PlanBRouteConflictError`, 일정이 그대로면 `PlanBStaleError` 다.
        재확인은 조회(API-014, GET)와 같은 빈 context 로 해서 조회 때 보인 안과 같은 기준으로 고른다.
        """
        _, block_id, _ = self._parse(option_id)
        if self._block(record, block_id).is_fixed:
            raise EngineInputError("Fixed blocks have no plan B")
        current = self.options(record, block_id, CalculationContext())
        if not any(option.id == option_id and option.available for option in current.options):
            raise PlanBStaleError
        block = self._block(record, block_id)
        base = self.engine.project(ValidateInput(trip=record.trip, schedule=record.schedule), context=context)
        result, new_id = self._compute(record, option_id, context, self.engine)
        rename = {new_id: block_id} if new_id != block_id else None
        if result.state == record.schedule:
            raise PlanBStaleError
        if not _timing_flags(result, block.day_no, rename) <= _timing_flags(base, block.day_no):
            raise PlanBRouteConflictError
        return result

    def _parse(self, option_id: str) -> tuple[str, str, str]:
        kind, _, rest = option_id.partition(":")
        block_id, _, argument = rest.partition(":")
        if kind not in {"REORDER", "REPLACE"} or not block_id or not argument:
            raise EngineInputError("Unknown plan B option")
        if kind == "REORDER" and SEQ_PATTERN.fullmatch(argument) is None:
            raise EngineInputError("Unknown plan B option")
        return kind, block_id, argument

    def _compute(
        self, record: TripRecord, option_id: str, context: CalculationContext, engine: ItineraryEngine
    ) -> tuple[EngineResult, str]:
        kind, block_id, argument = self._parse(option_id)
        block = self._block(record, block_id)
        if block.is_fixed:
            raise EngineInputError("Fixed blocks have no plan B")
        if kind == "REORDER":
            command = update_command(UpdateBlockRequest(seq=int(argument)), record.trip, record.schedule, block_id)
            return self._run(engine, command, context), block_id
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
        return self._run(engine, command, context), new_id

    # ---------- 공통 ----------

    @staticmethod
    def _run(
        engine: ItineraryEngine, command: RecomputeInput | ValidateInput, context: CalculationContext
    ) -> EngineResult:
        if isinstance(command, RecomputeInput):
            return engine.recompute(command, context=context)
        return engine.project(command, context=context)

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


class _Evaluator:
    """조회 한 번 안에서 안 하나를 계산한다. 고를 수 없으면 이유(Reason)를 돌려준다."""

    def __init__(
        self,
        planner: PlanBPlanner,
        record: TripRecord,
        block: StoredBlock,
        base_flags: set[tuple[str, str]],
        base_travel: int | None,
        context: CalculationContext,
        engine: ItineraryEngine,
    ) -> None:
        self.planner = planner
        self.record = record
        self.block = block
        self.base_flags = base_flags
        self.base_travel = base_travel
        self.context = context
        self.engine = engine

    def __call__(self, option_id: str, crowd: PlaceCrowdResponse | None) -> _Evaluated | Reason:
        planner, record, day_no = self.planner, self.record, self.block.day_no
        try:
            result, new_id = planner._compute(record, option_id, self.context, self.engine)
        except EngineInputError:
            return "UNSUITABLE"
        except (PolicyRequiredError, NeedsConfirmationError):
            return "ENGINE"
        replaced = new_id != self.block.id
        if not _timing_flags(result, day_no, {new_id: self.block.id} if replaced else None) <= self.base_flags:
            return "CONFLICT"
        target = next((b for b in _day_blocks(result, day_no) if b.id == new_id), None)
        if target is None or target.arrive_at is None or target.depart_at is None:
            return "UNKNOWN_TIME"
        if replaced:
            # 대체 장소: 공공 장소이고, 자신에게 영업시간 충돌 등 확인할 수 없는 경고가 없어야 한다.
            if not isinstance(target.place, PlaceSummary) or any(
                w.type not in REPLACEMENT_ALLOWED_WARNINGS for w in target.warnings
            ):
                return "UNSUITABLE"
            stored = next(b for b in result.state.blocks if b.id == new_id)
            crowd = planner._lookup(stored, record.trip.start_date + timedelta(days=day_no - 1))
        summary, cost = crowd_at_stay(crowd, target.arrive_at, target.depart_at, planner.min_confidence)
        travel = _day_travel(result.state, day_no)
        return _Evaluated(
            option_id=option_id,
            result=result,
            block=target,
            cost=cost,
            crowd=summary,
            extra=None if travel is None or self.base_travel is None else travel - self.base_travel,
            hours_conflict=planner._hours_conflict(_day_blocks(result, day_no)),
        )
