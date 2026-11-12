"""PUBLIC-only waypoint evaluation; no repository writes or retained request context."""

from collections import Counter
from datetime import date, timedelta
from typing import Protocol

from pydantic import Field

from app.modules.engine.constraints.chain import validate_chain
from app.modules.engine.interfaces import PlaceDataProvider, RouteProvider
from app.modules.engine.routing import departure_for, estimate_departing
from app.modules.engine.schemas import (
    BlockDraft,
    CalculationContext,
    ContractModel,
    InsertInput,
    KakaoPlaceRef,
    PublicPlaceRef,
    ScheduleState,
    TransientPlaceDetails,
    ValidateInput,
)
from app.modules.engine.service import (
    BasicItineraryEngine,
    EngineInputError,
    NeedsConfirmationError,
)
from app.modules.trips.repository import TripRecord
from app.modules.trips.schemas import (
    CrowdSummary,
    PlaceSummary,
    SuggestWaypointsRequest,
    SuggestWaypointsResponse,
    WaypointCandidate,
)


class CandidateData(ContractModel):
    ref: PublicPlaceRef
    stay_min: int | None = Field(default=None, gt=0)
    preference_match: float = Field(allow_inf_nan=False)
    representativeness: float = Field(allow_inf_nan=False)
    crowd: CrowdSummary | None = None
    crowd_penalty: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class CandidateProvider(Protocol):
    def candidates(self, *, on_date: date) -> tuple[CandidateData, ...]: ...


class ScoreWeights(ContractModel):
    """Explicit configuration: SDD gives terms, but no numerical defaults/scales."""

    preference: float = Field(ge=0, allow_inf_nan=False)
    representativeness: float = Field(ge=0, allow_inf_nan=False)
    detour: float = Field(ge=0, allow_inf_nan=False)
    crowd: float = Field(ge=0, allow_inf_nan=False)
    missing_crowd_penalty: float = Field(ge=0, allow_inf_nan=False)

    def score(self, candidate: CandidateData, detour: int) -> float:
        penalty = candidate.crowd_penalty if candidate.crowd is not None else None
        if penalty is None:
            penalty = self.missing_crowd_penalty
        return (
            self.preference * candidate.preference_match
            + self.representativeness * candidate.representativeness
            - self.detour * detour
            - self.crowd * penalty
        )


class WaypointRecommender:
    def __init__(
        self,
        candidates: CandidateProvider,
        places: PlaceDataProvider,
        routes: RouteProvider,
        weights: ScoreWeights,
    ) -> None:
        self.candidates = candidates
        self.places = places
        self.routes = routes
        self.weights = weights

    def _place(
        self, ref: PublicPlaceRef | KakaoPlaceRef, day: date, context: CalculationContext
    ) -> TransientPlaceDetails:
        if isinstance(ref, KakaoPlaceRef):
            coords = context.session_coords.get(ref.kakao_place_id)
            return TransientPlaceDetails(
                place_ref=ref,
                lat=coords.lat if coords else None,
                lng=coords.lng if coords else None,
            )
        details = self.places.get(ref, on_date=day)
        if details.place_ref != ref:
            raise EngineInputError("Place reference mismatch")
        return details

    def suggest(
        self, record: TripRecord, request: SuggestWaypointsRequest, context: CalculationContext
    ) -> SuggestWaypointsResponse:
        blocks = record.schedule.blocks
        index = next((i for i, block in enumerate(blocks) if block.id == request.from_block_id), None)
        if index is None or index + 1 >= len(blocks) or blocks[index + 1].id != request.to_block_id:
            raise EngineInputError("Waypoint endpoints must be adjacent")
        before, after = blocks[index : index + 2]
        if before.day_no != after.day_no:
            raise EngineInputError("Waypoint endpoints must be on the same day")
        if before.depart_at is None:
            return SuggestWaypointsResponse()
        day = record.trip.start_date + timedelta(days=before.day_no - 1)
        origin = self._place(before.place_ref, day, context)
        destination = self._place(after.place_ref, day, context)
        if any(value is None for value in (origin.lat, origin.lng, destination.lat, destination.lng)):
            return SuggestWaypointsResponse()
        anchor_check = validate_chain(
            ValidateInput(trip=record.trip, schedule=ScheduleState(blocks=(before,))),
            {before.id: origin},
        )
        if any(warning.type != "HOURS_NEEDS_CHECK" for warning in anchor_check.violations):
            return SuggestWaypointsResponse()
        departure = departure_for(record.trip, before)
        if departure is None:
            return SuggestWaypointsResponse()
        baseline_result = estimate_departing(
            self.routes,
            origin,
            destination,
            mode=record.trip.transport_mode,
            departure_at=departure,
        )
        baseline = baseline_result.duration_min
        if baseline is None or baseline < 0:
            return SuggestWaypointsResponse()

        # Simulate only the affected day. Other dates cannot change or veto this slot.
        day_blocks = tuple(block for block in blocks if block.day_no == before.day_no)
        ids = {block.id for block in day_blocks}
        state = ScheduleState(
            blocks=day_blocks,
            legs=tuple(leg for leg in record.schedule.legs if leg.from_block_id in ids and leg.to_block_id in ids),
        )
        probe_id = "waypoint-probe"
        while probe_id in ids:
            probe_id += "-"
        engine = BasicItineraryEngine(self.places, self.routes)
        offered = self.candidates.candidates(on_date=day)
        counts = Counter(candidate.ref.place_id for candidate in offered)
        ranked: list[tuple[float, str, WaypointCandidate]] = []
        affected = {block.id for block in blocks[index + 1 :] if block.day_no == before.day_no}
        for candidate in offered:
            if candidate.stay_min is None or counts[candidate.ref.place_id] != 1:
                continue
            if candidate.ref in (before.place_ref, after.place_ref):
                continue
            try:
                result = engine.insert(
                    InsertInput(
                        trip=record.trip,
                        schedule=state,
                        block=BlockDraft(
                            place_ref=candidate.ref,
                            is_fixed=False,
                            stay_min=candidate.stay_min,
                            origin="SUGGESTED",
                        ),
                        from_block_id=before.id,
                        to_block_id=after.id,
                        block_id=probe_id,
                    ),
                    context=context,
                )
            except NeedsConfirmationError:
                # Required PUBLIC metadata is unavailable, so do not fabricate a candidate.
                continue
            projected = [block for day_result in result.schedule.days for block in day_result.blocks]
            inserted = next(block for block in projected if block.id == probe_id)
            if any(w.type != "ROUTE_TIME_CONTEXT_ONLY" for w in inserted.warnings) or not isinstance(
                inserted.place, PlaceSummary
            ):
                continue
            # Unknown existing anchor hours remain unknown; never describe them as verified.
            # Candidate hours and all affected timing/route constraints must be verifiable.
            if any(
                block.id in affected
                and any(w.type not in {"HOURS_NEEDS_CHECK", "ROUTE_TIME_CONTEXT_ONLY"} for w in block.warnings)
                for block in projected
            ):
                continue
            via = [
                leg.duration_min
                for leg in result.state.legs
                if (leg.from_block_id, leg.to_block_id) in ((before.id, probe_id), (probe_id, after.id))
            ]
            if len(via) != 2 or any(duration is None for duration in via):
                continue
            detour = sum(duration for duration in via if duration is not None) - baseline
            if detour > request.threshold_min:
                continue
            unknown_hours = bool(anchor_check.violations) or any(
                block.id in affected and any(w.type == "HOURS_NEEDS_CHECK" for w in block.warnings)
                for block in projected
            )
            reason = f"우회 {detour}분·체류 {candidate.stay_min}분, 후보 영업시간과 후속 시간 제약 확인"
            if unknown_hours:
                reason += "; 기존 장소 영업시간은 별도 확인 필요"
            if baseline_result.time_semantics in {
                "service_availability",
                "search_context",
                "static",
            } or any(w.type == "ROUTE_TIME_CONTEXT_ONLY" for block in projected for w in block.warnings):
                reason += "; 출발시각별 시간표·교통 예측은 아님"
            ranked.append(
                (
                    self.weights.score(candidate, detour),
                    candidate.ref.place_id,
                    WaypointCandidate(
                        place=inserted.place,
                        detour_min=detour,
                        stay_min=candidate.stay_min,
                        crowd=candidate.crowd,
                        reason=reason,
                    ),
                )
            )
        ranked.sort(key=lambda row: (-row[0], row[1]))
        return SuggestWaypointsResponse(candidates=tuple(row[2] for row in ranked[:3]))
