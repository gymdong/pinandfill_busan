"""Read-only checks on a calculated schedule; missing data is never a pass."""

from collections import defaultdict
from collections.abc import Mapping
from datetime import time

from app.modules.engine.routing import departure_for
from app.modules.engine.schemas import (
    ScheduleConflict,
    StoredBlock,
    TransientPlaceDetails,
    ValidateInput,
    ValidationResult,
    Violation,
)


def minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def validate_chain(command: ValidateInput, places: Mapping[str, TransientPlaceDetails]) -> ValidationResult:
    warnings: dict[str, list[Violation]] = defaultdict(list)
    conflicts: list[ScheduleConflict] = []

    def report(block: StoredBlock, code: str, cause: str, *, conflict: bool = False) -> None:
        warnings[block.id].append(Violation(type=code, cause=cause))
        if conflict:
            conflicts.append(ScheduleConflict(cause=cause, block_ids=(block.id,)))

    # Opening-hours and closed-day checks are independent of travel-time checks.
    for block in command.schedule.blocks:
        details = places[block.id]
        if details.lat is None or details.lng is None:
            report(block, "COORDS_NEEDS_CHECK", "장소 좌표가 없어 다시 선택 또는 확인이 필요합니다.")
        hours = details.hours
        if hours is None:
            report(block, "HOURS_NEEDS_CHECK", "영업시간·휴무 정보 확인이 필요합니다.")
        elif hours.is_closed:
            report(block, "CLOSED_DAY", "방문일은 휴무일입니다.")
        elif hours.open_time is None or hours.close_time is None:
            report(block, "HOURS_NEEDS_CHECK", "영업 시작·종료 시각 확인이 필요합니다.")
        elif hours.close_time <= hours.open_time:
            report(
                block,
                "HOURS_NEEDS_CHECK",
                "자정을 넘기거나 해석되지 않은 영업시간의 확인이 필요합니다.",
            )
        elif block.arrive_at is not None and block.depart_at is not None:
            if block.arrive_at < hours.open_time or block.depart_at > hours.close_time:
                report(block, "OPENING_HOURS", "방문 시간이 영업시간을 벗어납니다.")
            if (hours.break_start is None) != (hours.break_end is None):
                report(block, "HOURS_NEEDS_CHECK", "브레이크타임 정보 확인이 필요합니다.")
            elif hours.break_start is not None and hours.break_end is not None:
                if hours.break_start >= hours.break_end:
                    report(block, "HOURS_NEEDS_CHECK", "브레이크타임 구간 확인이 필요합니다.")
                elif block.arrive_at < hours.break_end and block.depart_at > hours.break_start:
                    report(block, "BREAK_TIME", "방문 시간이 브레이크타임과 겹칩니다.")

        if block.is_fixed:
            if block.fixed_start is None or block.fixed_end is None:
                report(block, "FIXED_TIME_NEEDS_CHECK", "고정 블록의 지정 시간 확인이 필요합니다.")
            elif (block.arrive_at, block.depart_at) != (block.fixed_start, block.fixed_end):
                report(
                    block,
                    "FIXED_TIME_CONFLICT",
                    "계산 시각이 지정된 고정 시각과 다릅니다.",
                    conflict=True,
                )

        if block.arrive_at is None or block.depart_at is None:
            report(block, "TIME_NEEDS_CHECK", "도착·출발 시각을 계산할 정보가 부족합니다.")
        elif block.depart_at < block.arrive_at:
            report(
                block,
                "TIME_WINDOW_UNSUPPORTED",
                "자정을 넘는 방문 구간의 확인이 필요합니다.",
                conflict=True,
            )
        else:
            if minutes(block.depart_at) - minutes(block.arrive_at) != block.stay_min:
                report(block, "STAY_CONFLICT", "방문 시간창과 지정 체류시간이 다릅니다.", conflict=True)
            if block.arrive_at < command.trip.day_start or block.depart_at > command.trip.day_end:
                report(
                    block,
                    "DAY_WINDOW_CONFLICT",
                    "방문 시간이 하루 여행 시간창을 벗어납니다.",
                    conflict=True,
                )

    legs = {(leg.from_block_id, leg.to_block_id): leg for leg in command.schedule.legs}
    for previous, block in zip(command.schedule.blocks, command.schedule.blocks[1:], strict=False):
        if previous.day_no != block.day_no:
            continue
        leg = legs.get((previous.id, block.id))
        if departure_for(command.trip, previous) is None:
            report(
                block,
                "DEPARTURE_TIME_NEEDS_CHECK",
                "출발 날짜·시각 또는 시간대 정보가 없어 경로 조회를 수행할 수 없습니다.",
            )
        if leg is not None and leg.lookup_failed:
            report(
                block,
                "ROUTE_LOOKUP_FAILED",
                "경로 조회에 실패하여 이동시간을 확인할 수 없습니다.",
            )
        if (
            leg is not None
            and leg.duration_min is not None
            and leg.time_semantics
            in (
                "service_availability",
                "search_context",
                "static",
            )
        ):
            report(
                block,
                "ROUTE_TIME_CONTEXT_ONLY",
                "공급자 이동시간이며 해당 출발시각의 시간표·교통 예측값은 아닙니다.",
            )
        if leg is None or leg.duration_min is None:
            report(block, "TRAVEL_TIME_NEEDS_CHECK", "구간 이동시간 확인이 필요합니다.")
        elif (
            not block.is_fixed
            and previous.depart_at is not None
            and block.arrive_at is None
            and minutes(previous.depart_at) + leg.duration_min + block.stay_min >= 24 * 60
        ):
            report(
                block,
                "DAY_OVERFLOW",
                "이동·체류시간이 날짜 경계를 넘어 날짜 분리 검토가 필요합니다.",
                conflict=True,
            )
        elif previous.depart_at is not None and block.arrive_at is not None:
            if minutes(previous.depart_at) + leg.duration_min > minutes(block.arrive_at):
                report(
                    block,
                    "TRAVEL_TIME_CONFLICT",
                    "이동시간 때문에 다음 블록 도착 시각을 지킬 수 없습니다.",
                    conflict=True,
                )
        else:
            report(
                block,
                "TRAVEL_TIME_NEEDS_CHECK",
                "연결 블록의 시각이 없어 이동시간 검증이 필요합니다.",
            )

    return ValidationResult(
        violations=tuple(item for block in command.schedule.blocks for item in warnings[block.id]),
        conflicts=tuple(conflicts),
        block_warnings={key: tuple(value) for key, value in warnings.items()},
    )
