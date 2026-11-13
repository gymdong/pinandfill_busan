"""Explicit-order, same-day engine. No database, cache, logger or external client.

The from-block is the already edited anchor: recompute preserves it and its
prefix, recalculating only later blocks on that day. Automatic placement and
cross-day edits require a later policy.
"""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

from app.modules.engine.constraints.chain import minutes, validate_chain
from app.modules.engine.interfaces import EngineResult, PlaceDataProvider, RouteProvider
from app.modules.engine.routing import departure_for, estimate_departing
from app.modules.engine.schemas import (
    CalculationContext,
    InsertInput,
    KakaoPlaceRef,
    RecomputeInput,
    ScheduleState,
    StoredBlock,
    StoredLeg,
    TransientPlaceDetails,
    TripWindow,
    ValidateInput,
    ValidationResult,
)
from app.modules.trips.schemas import (
    Block,
    KakaoBlockPlace,
    Leg,
    PlaceSummary,
    Schedule,
    ScheduleDay,
)


class EngineInputError(ValueError):
    """Invalid identifiers/slot; messages contain no request payload."""


class SequenceNormalizationRequiredError(EngineInputError):
    """Legacy positions require a separate explicit migration, never an edit side effect."""


class PolicyRequiredError(ValueError):
    """Unsupported placement/time policy; the input schedule remains intact."""


class NeedsConfirmationError(ValueError):
    """Required public display metadata is unavailable; never fabricate it."""


def _now() -> datetime:
    return datetime.now(UTC)


class BasicItineraryEngine:
    def __init__(
        self,
        places: PlaceDataProvider,
        routes: RouteProvider,
        *,
        clock: Callable[[], datetime] = _now,
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        # Request-specific coordinates are intentionally never stored on self.
        self.places = places
        self.routes = routes
        self.clock = clock
        self.id_factory = id_factory

    def _check(self, trip: TripWindow, state: ScheduleState) -> None:
        if trip.day_end <= trip.day_start:
            raise PolicyRequiredError("Overnight day windows need an agreed policy")
        ids = [block.id for block in state.blocks]
        if len(ids) != len(set(ids)):
            raise EngineInputError("Block identifiers must be unique")
        positions = [(block.day_no, block.seq) for block in state.blocks]
        if positions != sorted(set(positions)):
            raise EngineInputError("Blocks must have unique, increasing day/sequence positions")
        days = (trip.end_date - trip.start_date).days + 1
        if any(block.day_no > days for block in state.blocks):
            raise EngineInputError("Block day is outside the trip dates")
        pairs = {(a.id, b.id) for a, b in zip(state.blocks, state.blocks[1:], strict=False) if a.day_no == b.day_no}
        leg_pairs = [(leg.from_block_id, leg.to_block_id) for leg in state.legs]
        if len(leg_pairs) != len(set(leg_pairs)) or any(pair not in pairs for pair in leg_pairs):
            raise EngineInputError("Legs must uniquely connect adjacent blocks on the same day")

    def _resolve(
        self,
        trip: TripWindow,
        state: ScheduleState,
        context: CalculationContext,
    ) -> dict[str, TransientPlaceDetails]:
        result: dict[str, TransientPlaceDetails] = {}
        for block in state.blocks:
            ref = block.place_ref
            if isinstance(ref, KakaoPlaceRef):
                coords = context.session_coords.get(ref.kakao_place_id)
                # Kakao names/hours are never requested from a provider or invented.
                details = TransientPlaceDetails(
                    place_ref=ref,
                    lat=coords.lat if coords else None,
                    lng=coords.lng if coords else None,
                )
            else:
                details = self.places.get(ref, on_date=trip.start_date + timedelta(days=block.day_no - 1))
                if details.place_ref != ref:
                    raise EngineInputError("Place provider returned a different reference")
            result[block.id] = details
        return result

    def validate(self, command: ValidateInput, *, context: CalculationContext | None = None) -> ValidationResult:
        self._check(command.trip, command.schedule)
        places = self._resolve(command.trip, command.schedule, context or CalculationContext())
        return validate_chain(command, places)

    def project(self, command: ValidateInput, *, context: CalculationContext | None = None) -> EngineResult:
        """저장된 상태를 다시 계산하지 않고 응답 일정으로만 바꾼다(되돌리기·변경 없는 편집).

        경로를 조회하지 않고 상태(시각·구간·seq)를 그대로 돌려준다. 경고는 validate 와 같은 규칙으로 붙는다.
        """
        self._check(command.trip, command.schedule)
        places = self._resolve(command.trip, command.schedule, context or CalculationContext())
        validation = validate_chain(command, places)
        return EngineResult(
            state=command.schedule,
            schedule=self._present(command.trip, command.schedule, places, validation),
        )

    def normalize_sequences(self, trip: TripWindow, state: ScheduleState, *, day_no: int) -> ScheduleState:
        """Explicit legacy migration only; callers must snapshot/commit it separately from edits.

        Preserve IDs, times, legs and other dates. Never invoked by insert/recompute.
        """
        self._check(trip, state)
        if not 1 <= day_no <= (trip.end_date - trip.start_date).days + 1:
            raise EngineInputError("Normalization day is outside the trip dates")
        position = 0
        blocks = []
        for block in state.blocks:
            if block.day_no == day_no:
                position += 1
                block = block.model_copy(update={"seq": position})
            blocks.append(block)
        return ScheduleState(blocks=tuple(blocks), legs=state.legs)

    def recompute(self, command: RecomputeInput, *, context: CalculationContext | None = None) -> EngineResult:
        self._check(command.trip, command.schedule)
        anchor = next(
            (i for i, b in enumerate(command.schedule.blocks) if b.id == command.from_block_id),
            None,
        )
        if anchor is None:
            raise EngineInputError("Recompute anchor does not exist")
        return self._calculate(command.trip, command.schedule, anchor, context or CalculationContext())

    def insert(self, command: InsertInput, *, context: CalculationContext | None = None) -> EngineResult:
        self._check(command.trip, command.schedule)
        blocks = list(command.schedule.blocks)
        if command.from_block_id is None and command.to_block_id is None:
            day_no = command.day_no
            if day_no is None and command.block.fixed_window is not None:
                day_no = command.block.fixed_window.day_no
            if day_no is None:
                raise EngineInputError("Insertion position or dayNo is required")
            day_indices = [i for i, block in enumerate(blocks) if block.day_no == day_no]
            index = (
                day_indices[-1]
                if day_indices
                else next((i - 1 for i, block in enumerate(blocks) if block.day_no > day_no), len(blocks) - 1)
            )
        else:
            if command.from_block_id is None or command.to_block_id is None:
                raise EngineInputError("Both insertion anchors are required")
            index = next((i for i, block in enumerate(blocks) if block.id == command.from_block_id), -1)
            if index < 0 or index + 1 >= len(blocks) or blocks[index + 1].id != command.to_block_id:
                raise EngineInputError("Insertion anchors must be adjacent")
            day_no = blocks[index].day_no
            if blocks[index + 1].day_no != day_no:
                raise EngineInputError("Insertion anchors must be on the same day")
            if command.day_no is not None and command.day_no != day_no:
                raise EngineInputError("dayNo must match the insertion anchors")
        if not 1 <= day_no <= (command.trip.end_date - command.trip.start_date).days + 1:
            raise EngineInputError("Insertion day is outside the trip dates")
        day_blocks = [block for block in blocks if block.day_no == day_no]
        if [block.seq for block in day_blocks] != list(range(1, len(day_blocks) + 1)):
            raise SequenceNormalizationRequiredError("Explicit legacy sequence migration is required")
        first_on_day = not day_blocks
        seq = blocks[index].seq + 1 if not first_on_day else 1
        draft = command.block
        window = draft.fixed_window
        if window is not None and window.day_no != day_no:
            raise EngineInputError("Fixed window must match the insertion day")
        if window is not None and not draft.is_fixed:
            raise EngineInputError("A fixed window requires a fixed block")
        block_id = command.block_id or self.id_factory()
        if block_id in {b.id for b in blocks}:
            raise EngineInputError("New block identifier already exists")
        blocks.insert(
            index + 1,
            StoredBlock(
                id=block_id,
                day_no=day_no,
                seq=seq,
                place_ref=draft.place_ref,
                is_fixed=draft.is_fixed,
                fixed_start=window.start if window else None,
                fixed_end=window.end if window else None,
                stay_min=draft.stay_min,
                arrive_at=window.start if window else None,
                depart_at=window.end if window else None,
                origin=draft.origin,
            ),
        )
        for block_index in range(index + 2, len(blocks)):
            existing = blocks[block_index]
            if existing.day_no == day_no:
                blocks[block_index] = existing.model_copy(update={"seq": existing.seq + 1})
        replaced_pair = (command.from_block_id, command.to_block_id)
        state = ScheduleState(
            blocks=tuple(blocks),
            legs=tuple(leg for leg in command.schedule.legs if (leg.from_block_id, leg.to_block_id) != replaced_pair),
        )
        return self._calculate(
            command.trip, state, index + 1 if first_on_day else index, context or CalculationContext()
        )

    def _calculate(
        self,
        trip: TripWindow,
        state: ScheduleState,
        anchor: int,
        context: CalculationContext,
    ) -> EngineResult:
        places = self._resolve(trip, state, context)
        blocks = list(state.blocks)
        legs = {(leg.from_block_id, leg.to_block_id): leg for leg in state.legs}
        for index in range(anchor + 1, len(blocks)):
            previous, block = blocks[index - 1], blocks[index]
            if block.day_no != blocks[anchor].day_no:
                break
            origin, destination = places[previous.id], places[block.id]
            pair = (previous.id, block.id)
            duration: int | None = None
            source = "UNKNOWN"
            computed_at = None
            time_semantics = "unspecified"
            lookup_failed = False
            departure = departure_for(trip, previous)
            if departure is not None and all(
                value is not None for value in (origin.lat, origin.lng, destination.lat, destination.lng)
            ):
                estimate = estimate_departing(
                    self.routes,
                    origin,
                    destination,
                    mode=trip.transport_mode,
                    departure_at=departure,
                )
                duration, source, computed_at = (
                    estimate.duration_min,
                    estimate.source,
                    estimate.computed_at,
                )
                time_semantics = estimate.time_semantics
                lookup_failed = estimate.lookup_failed or duration is None
                if duration is None or lookup_failed:
                    duration, source = None, "UNKNOWN"
            legs[pair] = StoredLeg.model_validate(
                {
                    "id": legs[pair].id if pair in legs else self.id_factory(),
                    "from_block_id": previous.id,
                    "to_block_id": block.id,
                    "mode": trip.transport_mode,
                    "duration_min": duration,
                    "source": source,
                    "computed_at": computed_at,
                    "time_semantics": time_semantics,
                    "lookup_failed": lookup_failed,
                }
            )
            if block.is_fixed:
                arrive = block.fixed_start if block.fixed_start is not None else block.arrive_at
                depart = block.fixed_end if block.fixed_end is not None else block.depart_at
            else:
                arrive = depart = None
                if previous.depart_at is not None and duration is not None:
                    start = minutes(previous.depart_at) + duration
                    end = start + block.stay_min
                    if end < 24 * 60:
                        arrive, depart = time(start // 60, start % 60), time(end // 60, end % 60)
            blocks[index] = block.model_copy(update={"arrive_at": arrive, "depart_at": depart})
        updated = ScheduleState(blocks=tuple(blocks), legs=tuple(legs.values()))
        validation = validate_chain(ValidateInput(trip=trip, schedule=updated), places)
        return EngineResult(state=updated, schedule=self._present(trip, updated, places, validation))

    def _present(
        self,
        trip: TripWindow,
        state: ScheduleState,
        places: Mapping[str, TransientPlaceDetails],
        validation: ValidationResult,
    ) -> Schedule:
        days: list[ScheduleDay] = []
        for day_no in range(1, (trip.end_date - trip.start_date).days + 2):
            response_blocks: list[Block] = []
            for block in state.blocks:
                if block.day_no != day_no:
                    continue
                ref, details = block.place_ref, places[block.id]
                place: PlaceSummary | KakaoBlockPlace
                if isinstance(ref, KakaoPlaceRef):
                    place = KakaoBlockPlace(kakao_place_id=ref.kakao_place_id, place_url=ref.kakao_place_url)
                else:
                    if (
                        details.name is None
                        or details.lat is None
                        or details.lng is None
                        or details.category is None
                        or details.ref_date is None
                    ):
                        raise NeedsConfirmationError("Public place display information needs confirmation")
                    place = PlaceSummary(
                        id=ref.place_id,
                        name=details.name,
                        lat=details.lat,
                        lng=details.lng,
                        category=details.category,
                        ref_date=details.ref_date,
                        source="PUBLIC",
                    )
                response_blocks.append(
                    Block(
                        id=block.id,
                        day_no=block.day_no,
                        seq=block.seq,
                        place=place,
                        is_fixed=block.is_fixed,
                        fixed_start=block.fixed_start,
                        fixed_end=block.fixed_end,
                        stay_min=block.stay_min,
                        arrive_at=block.arrive_at,
                        depart_at=block.depart_at,
                        origin=block.origin,
                        warnings=validation.block_warnings.get(block.id, ()),
                    )
                )
            ids = {b.id for b in response_blocks}
            response_legs: list[Leg] = []
            for leg in state.legs:
                if leg.from_block_id in ids and leg.to_block_id in ids:
                    # The existing wire enum has no UNKNOWN. Never emit a false source.
                    # Missing legs are represented by block/schedule warnings until
                    # frontend LegSource/nullable computedAt are jointly extended.
                    if leg.duration_min is None or leg.source == "UNKNOWN" or leg.lookup_failed:
                        continue
                    if leg.computed_at is None:
                        raise NeedsConfirmationError("Existing route computation timestamp needs confirmation")
                    response_legs.append(
                        Leg.model_validate(leg.model_dump(exclude={"time_semantics", "lookup_failed"}))
                    )
            days.append(
                ScheduleDay(
                    day_no=day_no,
                    date=trip.start_date + timedelta(days=day_no - 1),
                    blocks=tuple(response_blocks),
                    legs=tuple(response_legs),
                )
            )
        return Schedule(days=tuple(days), violations=validation.violations, conflicts=validation.conflicts)
