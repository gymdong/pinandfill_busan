"""Bounded, deterministic initial scheduling without invented facts.

This module is engine-only.  It deliberately does not change API-009's public
request contract; a later adapter can translate an agreed selection contract.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator

from app.modules.engine.constraints.chain import minutes, validate_chain
from app.modules.engine.interfaces import RouteEstimate
from app.modules.engine.routing import estimate_departing, seoul_datetime
from app.modules.engine.schemas import (
    CalculationContext,
    ContractModel,
    FixedWindow,
    KakaoPlaceRef,
    PlaceRef,
    ScheduleConflict,
    ScheduleState,
    StoredBlock,
    StoredLeg,
    TransientPlaceDetails,
    TripWindow,
    ValidateInput,
    Violation,
)
from app.modules.engine.service import BasicItineraryEngine, EngineInputError, NeedsConfirmationError
from app.modules.trips.schemas import Schedule


class StayDurationProvider(Protocol):
    """Public-place duration boundary (for example places.default_stay_min)."""

    def get(self, place_ref: PlaceRef, *, on_date: date) -> int | None: ...


class TagStayPolicy(Protocol):
    """Optional policy boundary; disabled until an agreed policy is injected."""

    def get(self, place_ref: PlaceRef, *, on_date: date) -> int | None: ...


class InitialSelection(ContractModel):
    """One selected core place; fixedWindow is the only timed hard lock."""

    block_id: str = Field(min_length=1)
    place_ref: PlaceRef
    stay_min: int | None = Field(default=None, gt=0)
    fixed_window: FixedWindow | None = None
    allowed_days: tuple[int, ...] | None = None
    origin: Literal["USER", "SUGGESTED"] = "USER"

    @model_validator(mode="after")
    def valid_days(self) -> InitialSelection:
        if self.allowed_days is not None and (not self.allowed_days or any(day < 1 for day in self.allowed_days)):
            raise ValueError("allowedDays must contain positive day numbers")
        if (
            self.fixed_window is not None
            and self.allowed_days is not None
            and self.fixed_window.day_no not in self.allowed_days
        ):
            raise ValueError("fixedWindow day must be allowed")
        return self


class InitialScheduleCommand(ContractModel):
    trip: TripWindow
    selections: tuple[InitialSelection, ...]
    # Required so the engine never silently chooses a business ordering policy.
    policy: Literal["FIRST_FEASIBLE"]

    @model_validator(mode="after")
    def unique_ids(self) -> InitialScheduleCommand:
        ids = [item.block_id for item in self.selections]
        if len(ids) != len(set(ids)):
            raise ValueError("selection block identifiers must be unique")
        return self


class UnplacedSelection(ContractModel):
    block_id: str = Field(min_length=1)
    reason: Violation


class InitialScheduleResult(ContractModel):
    state: ScheduleState
    schedule: Schedule | None = None
    unplaced: tuple[UnplacedSelection, ...] = ()
    violations: tuple[Violation, ...] = ()
    conflicts: tuple[ScheduleConflict, ...] = ()
    confirmed: bool = False


@dataclass(frozen=True)
class _Resolved:
    selection: InitialSelection
    stay_min: int


@dataclass(frozen=True)
class _Day:
    blocks: tuple[StoredBlock, ...]
    legs: tuple[StoredLeg, ...]
    feasible: bool
    exact: bool
    reason: Violation | None = None
    conflicts: tuple[ScheduleConflict, ...] = ()


class InitialSchedulePlanner:
    """SDD ADR-003 insertion heuristic with a deliberately bounded policy.

    Flexible selections are processed in caller order.  Days and insertion gaps
    are tried in ascending order.  An unplaced result only means this bounded
    policy could not verify a slot; it is not a proof that no global solution
    exists.
    """

    def __init__(
        self,
        engine: BasicItineraryEngine,
        stay_durations: StayDurationProvider,
        *,
        tag_stays: TagStayPolicy | None = None,
    ) -> None:
        self.engine = engine
        self.stay_durations = stay_durations
        self.tag_stays = tag_stays

    def plan(
        self,
        command: InitialScheduleCommand,
        *,
        context: CalculationContext | None = None,
    ) -> InitialScheduleResult:
        if command.trip.day_end <= command.trip.day_start:
            raise EngineInputError("Overnight trip windows need an agreed policy")
        day_count = (command.trip.end_date - command.trip.start_date).days + 1
        request_context = context or CalculationContext()
        resolved: dict[str, _Resolved] = {}
        unplaced: list[UnplacedSelection] = []

        for item in command.selections:
            if item.fixed_window is not None and item.fixed_window.day_no > day_count:
                raise EngineInputError("Fixed selection day is outside the trip dates")
            if item.fixed_window is None:
                continue
            duration = self._stay(item, command.trip.start_date + timedelta(days=item.fixed_window.day_no - 1))
            if duration is None:
                unplaced.append(self._unplaced(item, "STAY_NEEDS_CHECK", "체류시간 근거 확인이 필요합니다."))
            else:
                resolved[item.block_id] = _Resolved(item, duration)

        by_day: dict[int, list[_Resolved]] = {day: [] for day in range(1, day_count + 1)}
        flexible: list[InitialSelection] = []
        extra_violations: list[Violation] = []
        extra_conflicts: list[ScheduleConflict] = []
        details_cache: dict[tuple[str, date], TransientPlaceDetails] = {}
        accepted: dict[int, _Day] = {}
        previous_fixed_position: tuple[int, time] | None = None

        # Preserve the caller's relative order for fixed selections.  Sorting by
        # time would silently rewrite an explicit pin order.
        for item in command.selections:
            if item.fixed_window is None:
                flexible.append(item)
            else:
                selected = resolved.get(item.block_id)
                if selected is None:
                    continue
                fixed_position = (item.fixed_window.day_no, item.fixed_window.start)
                if previous_fixed_position is not None and fixed_position < previous_fixed_position:
                    cause = "고정 장소의 입력 순서와 지정 날짜·시각 순서가 일치하지 않습니다."
                    extra_violations.append(Violation(type="FIXED_ORDER_CONFLICT", cause=cause))
                    extra_conflicts.append(ScheduleConflict(cause=cause, block_ids=(item.block_id,)))
                previous_fixed_position = fixed_position
                by_day[item.fixed_window.day_no].append(selected)

        for day_no, items in by_day.items():
            checked = self._day(command.trip, day_no, items, request_context, details_cache, retain_fixed=True)
            accepted[day_no] = checked
            if checked.reason is not None:
                extra_violations.append(checked.reason)
                extra_conflicts.extend(checked.conflicts)

        for selection in flexible:
            allowed = selection.allowed_days or tuple(range(1, day_count + 1))
            valid_days = sorted({day for day in allowed if 1 <= day <= day_count})
            if not valid_days:
                unplaced.append(
                    self._unplaced(selection, "DAY_NEEDS_CHECK", "방문 가능한 날짜가 여행 기간에 없습니다.")
                )
                continue
            placed = False
            first_reason: Violation | None = None
            for day_no in valid_days:
                duration = self._stay(selection, command.trip.start_date + timedelta(days=day_no - 1))
                if duration is None:
                    first_reason = first_reason or Violation(
                        type="STAY_NEEDS_CHECK", cause="체류시간 근거 확인이 필요합니다."
                    )
                    continue
                candidate = _Resolved(selection, duration)
                for position in range(len(by_day[day_no]) + 1):
                    trial = list(by_day[day_no])
                    trial.insert(position, candidate)
                    checked = self._day(command.trip, day_no, trial, request_context, details_cache)
                    first_reason = first_reason or checked.reason
                    if checked.feasible:
                        by_day[day_no] = trial
                        accepted[day_no] = checked
                        placed = True
                        break
                if placed:
                    break
            if not placed:
                unplaced.append(
                    UnplacedSelection(
                        block_id=selection.block_id,
                        reason=first_reason
                        or Violation(
                            type="PLACEMENT_NEEDS_CHECK",
                            cause="현재 삽입 휴리스틱으로 배치 위치를 확인할 수 없습니다.",
                        ),
                    )
                )

        blocks: list[StoredBlock] = []
        legs: list[StoredLeg] = []
        exact = True
        for day_no in by_day:
            checked = accepted[day_no]
            blocks.extend(checked.blocks)
            legs.extend(checked.legs)
            exact = exact and checked.exact and checked.feasible
        state = ScheduleState(blocks=tuple(blocks), legs=tuple(legs))
        self.engine._check(command.trip, state)
        # Resolve through the sanitizing boundary used during placement.  A
        # provider outage must become confirmation-required metadata, not an
        # exception that can expose provider/request details.
        details = {
            block.id: details_cache[(block.id, command.trip.start_date + timedelta(days=block.day_no - 1))]
            for block in state.blocks
        }
        validation = validate_chain(ValidateInput(trip=command.trip, schedule=state), details)
        violations = (*validation.violations, *extra_violations, *(item.reason for item in unplaced))
        conflicts = (*validation.conflicts, *extra_conflicts)

        try:
            schedule = self.engine._present(command.trip, state, details, validation).model_copy(
                update={"violations": violations, "conflicts": conflicts}
            )
        except NeedsConfirmationError:
            schedule = None
            violations = (
                *violations,
                Violation(
                    type="PRESENTATION_NEEDS_CHECK",
                    cause="일정 표시용 공공 장소 정보 확인이 필요합니다.",
                ),
            )
        confirmed = not unplaced and not conflicts and exact and not violations
        return InitialScheduleResult(
            state=state,
            schedule=schedule,
            unplaced=tuple(unplaced),
            violations=violations,
            conflicts=conflicts,
            confirmed=confirmed,
        )

    def _stay(self, item: InitialSelection, on_date: date) -> int | None:
        if item.stay_min is not None:
            return item.stay_min
        if item.fixed_window is not None:
            window_duration = minutes(item.fixed_window.end) - minutes(item.fixed_window.start)
            return window_duration if window_duration > 0 else None
        if isinstance(item.place_ref, KakaoPlaceRef):
            return None
        duration: int | None
        try:
            duration = self.stay_durations.get(item.place_ref, on_date=on_date)
        except Exception:
            duration = None
        if duration is not None:
            return duration if type(duration) is int and duration > 0 else None
        if self.tag_stays is None:
            return None
        try:
            duration = self.tag_stays.get(item.place_ref, on_date=on_date)
        except Exception:
            return None
        return duration if type(duration) is int and duration > 0 else None

    def _details(self, ref: PlaceRef, on_date: date, context: CalculationContext) -> TransientPlaceDetails:
        if isinstance(ref, KakaoPlaceRef):
            coords = context.session_coords.get(ref.kakao_place_id)
            return TransientPlaceDetails(
                place_ref=ref,
                lat=coords.lat if coords else None,
                lng=coords.lng if coords else None,
            )
        try:
            details = self.engine.places.get(ref, on_date=on_date)
        except Exception:
            return TransientPlaceDetails(place_ref=ref)
        if details.place_ref != ref:
            raise EngineInputError("Place provider returned a different reference")
        return details

    def _day(
        self,
        trip: TripWindow,
        day_no: int,
        items: list[_Resolved],
        context: CalculationContext,
        details_cache: dict[tuple[str, date], TransientPlaceDetails],
        *,
        retain_fixed: bool = False,
    ) -> _Day:
        on_date = trip.start_date + timedelta(days=day_no - 1)
        blocks: list[StoredBlock] = []
        legs: list[StoredLeg] = []
        details: dict[str, TransientPlaceDetails] = {}
        exact = True
        failure: Violation | None = None
        conflicts: list[ScheduleConflict] = []

        for seq, item in enumerate(items, start=1):
            selected = item.selection
            key = (selected.block_id, on_date)
            if key not in details_cache:
                details_cache[key] = self._details(selected.place_ref, on_date, context)
            place = details_cache[key]
            details[selected.block_id] = place
            fixed = selected.fixed_window
            previous = blocks[-1] if blocks else None
            route: RouteEstimate | None = None
            duration: int | None = 0 if previous is None else None

            if previous is not None:
                origin = details[previous.id]
                departure = seoul_datetime(on_date, previous.depart_at) if previous.depart_at else None
                if departure is not None and all(
                    value is not None for value in (origin.lat, origin.lng, place.lat, place.lng)
                ):
                    try:
                        route = estimate_departing(
                            self.engine.routes,
                            origin,
                            place,
                            mode=trip.transport_mode,
                            departure_at=departure,
                        )
                    except Exception:
                        route = None
                    if route is not None and (
                        type(route.duration_min) is not int
                        or route.duration_min < 0
                        or route.source == "UNKNOWN"
                        or route.lookup_failed
                    ):
                        route = None
                    duration = route.duration_min if route is not None else None
                successful = route is not None and duration is not None and not route.lookup_failed
                if not successful:
                    duration = None
                    exact = False
                elif route is not None and (
                    route.source == "ESTIMATED"
                    or route.time_semantics
                    in {
                        "service_availability",
                        "search_context",
                        "static",
                    }
                ):
                    exact = False
                legs.append(self._leg(previous, selected.block_id, trip, route))

            arrive: time | None
            depart: time | None
            if fixed is not None:
                arrive, depart = fixed.start, fixed.end
                fixed_duration = minutes(depart) - minutes(arrive)
                if fixed.day_no != day_no or fixed_duration <= 0 or item.stay_min != fixed_duration:
                    failure = Violation(
                        type="FIXED_TIME_CONFLICT",
                        cause="고정 방문시간과 체류시간이 일치하지 않습니다.",
                    )
                if previous is not None:
                    if previous.depart_at is None or duration is None:
                        exact = False
                    elif minutes(previous.depart_at) + duration > minutes(arrive):
                        failure = Violation(
                            type="FIXED_ORDER_CONFLICT",
                            cause="입력 순서에서 고정 방문시간을 지킬 수 없습니다.",
                        )
                if failure is not None:
                    conflicts.append(ScheduleConflict(cause=failure.cause, block_ids=(selected.block_id,)))
            else:
                arrive, depart, failure = self._flexible_times(trip, previous, duration, item.stay_min, place)

            blocks.append(
                StoredBlock(
                    id=selected.block_id,
                    day_no=day_no,
                    seq=seq,
                    place_ref=selected.place_ref,
                    is_fixed=fixed is not None,
                    fixed_start=fixed.start if fixed else None,
                    fixed_end=fixed.end if fixed else None,
                    stay_min=item.stay_min,
                    arrive_at=arrive,
                    depart_at=depart,
                    origin=selected.origin,
                )
            )
            if failure is not None and not (retain_fixed and fixed is not None):
                return _Day(tuple(blocks), tuple(legs), False, False, failure, tuple(conflicts))

        return _Day(tuple(blocks), tuple(legs), failure is None, exact, failure, tuple(conflicts))

    def _flexible_times(
        self,
        trip: TripWindow,
        previous: StoredBlock | None,
        duration: int | None,
        stay: int,
        details: TransientPlaceDetails,
    ) -> tuple[time | None, time | None, Violation | None]:
        hours = details.hours
        if hours is not None and hours.is_closed:
            return None, None, Violation(type="CLOSED_DAY", cause="방문일은 휴무일입니다.")
        if hours is None or hours.open_time is None or hours.close_time is None:
            return None, None, Violation(type="HOURS_NEEDS_CHECK", cause="영업시간·휴무 정보 확인이 필요합니다.")
        if previous is not None and (previous.depart_at is None or duration is None):
            return (
                None,
                None,
                Violation(type="TRAVEL_TIME_NEEDS_CHECK", cause="이동시간 또는 출발시각 확인이 필요합니다."),
            )
        start = minutes(trip.day_start)
        if previous is not None and previous.depart_at is not None and duration is not None:
            start = minutes(previous.depart_at) + duration
        start = max(start, minutes(hours.open_time))
        if hours.break_start is not None and hours.break_end is not None:
            break_start, break_end = minutes(hours.break_start), minutes(hours.break_end)
            if break_start < break_end and start < break_end and start + stay > break_start:
                start = break_end
        end = start + stay
        if end >= 24 * 60:
            return (
                None,
                None,
                Violation(type="DAY_OVERFLOW", cause="방문이 날짜 경계를 넘어 날짜 분리 검토가 필요합니다."),
            )
        if end > minutes(trip.day_end) or end > minutes(hours.close_time):
            return None, None, Violation(type="TIME_WINDOW_CONFLICT", cause="여행·영업 시간창 안에 배치할 수 없습니다.")
        return time(start // 60, start % 60), time(end // 60, end % 60), None

    @staticmethod
    def _leg(
        previous: StoredBlock,
        to_id: str,
        trip: TripWindow,
        route: RouteEstimate | None,
    ) -> StoredLeg:
        successful = route is not None and route.duration_min is not None and not route.lookup_failed
        return StoredLeg(
            id=str(uuid5(NAMESPACE_URL, json.dumps(["pinandfill-initial-leg", previous.id, to_id]))),
            from_block_id=previous.id,
            to_block_id=to_id,
            mode=trip.transport_mode,
            duration_min=route.duration_min if successful and route is not None else None,
            source=route.source if successful and route is not None else "UNKNOWN",
            computed_at=route.computed_at if successful and route is not None else None,
            time_semantics=route.time_semantics if route is not None else "unspecified",
            lookup_failed=route.lookup_failed if route is not None else False,
        )

    @staticmethod
    def _unplaced(item: InitialSelection, code: str, cause: str) -> UnplacedSelection:
        return UnplacedSelection(block_id=item.block_id, reason=Violation(type=code, cause=cause))
