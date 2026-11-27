"""PUBLIC-only waypoint evaluation; no repository writes or retained request context."""

from collections import Counter
from collections.abc import Callable
from datetime import date, time, timedelta
from typing import Protocol

from pydantic import Field

from app.adapters.route.estimated import distance_km
from app.modules.crowd.avoidance import meets_confidence, window_cost
from app.modules.crowd.schemas import CrowdConfidence, PlaceCrowdResponse
from app.modules.engine.constraints.chain import validate_chain
from app.modules.engine.interfaces import CrowdLookup, PlaceDataProvider, RouteProvider
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


class PublicPlaceCandidates:
    """앱의 공공 장소 전체를 후보로 낸다(체류시간 근거가 있는 곳만). 선호·대표성 근거 자료가 아직 없어 0 이다."""

    def __init__(self, place_ids: Callable[[], list[str]], stay_min: Callable[[str], int | None]) -> None:
        self._place_ids = place_ids
        self._stay_min = stay_min

    def candidates(self, *, on_date: date) -> tuple[CandidateData, ...]:
        rows = []
        for place_id in sorted(self._place_ids()):
            stay = self._stay_min(place_id)
            if stay is not None and stay > 0:
                rows.append(
                    CandidateData(
                        ref=PublicPlaceRef(place_id=place_id),
                        stay_min=stay,
                        preference_match=0,
                        representativeness=0,
                    )
                )
        return tuple(rows)


def crowd_at_stay(
    crowd: PlaceCrowdResponse | None, arrive: time, depart: time, min_confidence: CrowdConfidence
) -> tuple[CrowdSummary | None, float | None]:
    """(도착 시각의 등급 요약, 점수 벌점). 벌점은 신뢰도가 기준 이상일 때만 체류 구간 평균 score 다.

    혼잡 정보가 없으면(None·'없음') 요약도 없다(화면 '정보 부족'). 신뢰도가 낮으면 요약만 보여 주고 벌점은 없다.
    """
    if crowd is None or crowd.confidence == "없음" or not crowd.hours:
        return None, None
    grade = next((hour.grade for hour in crowd.hours if hour.h == arrive.hour), None)
    summary = CrowdSummary(grade=grade, confidence=crowd.confidence, as_of=crowd.as_of, sources=tuple(crowd.sources))
    penalty = window_cost(crowd, arrive, depart) if meets_confidence(crowd, min_confidence) else None
    return summary, penalty


class WaypointRecommender:
    def __init__(
        self,
        candidates: CandidateProvider,
        places: PlaceDataProvider,
        routes: RouteProvider,
        weights: ScoreWeights,
        *,
        crowd: CrowdLookup | None = None,
        crowd_min_confidence: CrowdConfidence = "중간",
        max_route_candidates: int | None = None,
    ) -> None:
        self.candidates = candidates
        self.places = places
        self.routes = routes
        self.weights = weights
        # 후보에 혼잡이 없으면 넣은 위치의 도착~출발 시각으로 예상 혼잡을 계산한다(FR-004 후보별 예상 혼잡).
        self.crowd = crowd
        self.crowd_min_confidence = crowd_min_confidence
        # 경로를 조회해 볼 후보 수 상한. 넘으면 직선거리 우회가 짧은 순으로 자른다(경로 API 한도 보호).
        self.max_route_candidates = max_route_candidates

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

    def _nearest(
        self,
        offered: tuple[CandidateData, ...],
        origin: TransientPlaceDetails,
        destination: TransientPlaceDetails,
        day: date,
        context: CalculationContext,
    ) -> tuple[CandidateData, ...]:
        """직선거리 우회(출발→후보→도착 - 출발→도착)가 짧은 후보 max_route_candidates 개. 좌표 없는 후보는 뺀다."""
        direct = distance_km(origin, destination) or 0.0
        scored: list[tuple[float, str, CandidateData]] = []
        for candidate in offered:
            place = self._place(candidate.ref, day, context)
            first, second = distance_km(origin, place), distance_km(place, destination)
            if first is not None and second is not None:
                scored.append((first + second - direct, candidate.ref.place_id, candidate))
        scored.sort(key=lambda row: (row[0], row[1]))
        return tuple(row[2] for row in scored[: self.max_route_candidates])

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
        in_trip = {block.place_ref for block in blocks}
        offered = tuple(c for c in self.candidates.candidates(on_date=day) if c.ref not in in_trip)
        if self.max_route_candidates is not None and len(offered) > self.max_route_candidates:
            offered = self._nearest(offered, origin, destination, day, context)
        counts = Counter(candidate.ref.place_id for candidate in offered)
        ranked: list[tuple[float, str, WaypointCandidate]] = []
        affected = {block.id for block in blocks[index + 1 :] if block.day_no == before.day_no}
        for candidate in offered:
            if candidate.stay_min is None or counts[candidate.ref.place_id] != 1:
                continue
            # 이미 일정에 있는 장소(다른 날 포함)는 다시 제안하지 않는다.
            if candidate.ref in in_trip:
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
            via_legs = [
                leg
                for leg in result.state.legs
                if (leg.from_block_id, leg.to_block_id) in ((before.id, probe_id), (probe_id, after.id))
            ]
            via = [leg.duration_min for leg in via_legs]
            if len(via) != 2 or any(duration is None for duration in via):
                continue
            # 기준과 경유 구간의 출처가 다르면(예: 기준은 TMAP, 경유는 한도 초과로 추정) 차이가 음수일 수 있다.
            mixed = any(leg.source != baseline_result.source for leg in via_legs)
            detour = max(0, sum(duration for duration in via if duration is not None) - baseline)
            if detour > request.threshold_min:
                continue
            unknown_hours = bool(anchor_check.violations) or any(
                block.id in affected and any(w.type == "HOURS_NEEDS_CHECK" for w in block.warnings)
                for block in projected
            )
            reason = f"우회 {detour}분·체류 {candidate.stay_min}분, 후보 영업시간과 후속 시간 제약 확인"
            if unknown_hours:
                reason += "; 기존 장소 영업시간은 별도 확인 필요"
            if mixed:
                reason += "; 추정 이동시간 포함"
            if baseline_result.time_semantics in {
                "service_availability",
                "search_context",
                "static",
            } or any(w.type == "ROUTE_TIME_CONTEXT_ONLY" for block in projected for w in block.warnings):
                reason += "; 출발시각별 시간표·교통 예측은 아님"
            arrive, depart = inserted.arrive_at, inserted.depart_at
            if candidate.crowd is None and self.crowd is not None and arrive is not None and depart is not None:
                summary, penalty = crowd_at_stay(
                    self.crowd.crowd(candidate.ref, on_date=day),
                    arrive,
                    depart,
                    self.crowd_min_confidence,
                )
                scored = candidate.model_copy(update={"crowd": summary, "crowd_penalty": penalty})
            else:
                scored = candidate
            ranked.append(
                (
                    self.weights.score(scored, detour),
                    candidate.ref.place_id,
                    WaypointCandidate(
                        place=inserted.place,
                        detour_min=detour,
                        stay_min=candidate.stay_min,
                        crowd=scored.crowd,
                        reason=reason,
                    ),
                )
            )
        ranked.sort(key=lambda row: (-row[0], row[1]))
        return SuggestWaypointsResponse(candidates=tuple(row[2] for row in ranked[:3]))
