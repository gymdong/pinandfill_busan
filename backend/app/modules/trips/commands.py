"""Translate HTTP contracts without retaining request-only Kakao coordinates."""

from datetime import time

from app.modules.engine.constraints.chain import minutes
from app.modules.engine.schemas import (
    BlockDraft,
    CalculationContext,
    InsertInput,
    KakaoPlaceRef,
    PublicPlaceRef,
    RecomputeInput,
    ScheduleState,
    StoredBlock,
    TripWindow,
    ValidateInput,
)
from app.modules.engine.service import EngineInputError, PolicyRequiredError, SequenceNormalizationRequiredError
from app.modules.trips.schemas import AddBlockRequest, PublicPlaceInput, UpdateBlockRequest, WithSessionCoords


def calculation_context(request: WithSessionCoords) -> CalculationContext:
    # Copy the mapping: a caller mutating its request dictionary must not alter
    # an in-flight calculation. Coordinate values themselves are frozen models.
    return CalculationContext(session_coords=dict(request.session_coords))


def insert_command(
    request: AddBlockRequest,
    trip: TripWindow,
    schedule: ScheduleState,
    *,
    stay_min: int,
    block_id: str | None = None,
) -> InsertInput:
    """Stay duration must be resolved explicitly; no default for Kakao is invented.

    Call calculation_context separately and pass it only to this engine call.
    The returned command is suitable for non-sensitive command handling.
    """
    place_ref: PublicPlaceRef | KakaoPlaceRef
    if isinstance(request.place, PublicPlaceInput):
        place_ref = PublicPlaceRef(place_id=request.place.place_id)
    else:
        place_ref = KakaoPlaceRef.model_validate(
            {
                "kakaoPlaceId": request.place.kakao_place_id,
                "placeUrl": request.place.place_url,
            }
        )
    return InsertInput(
        trip=trip,
        schedule=schedule,
        block=BlockDraft(
            place_ref=place_ref,
            is_fixed=request.is_fixed,
            fixed_window=request.fixed_window,
            stay_min=stay_min,
            origin=request.origin,
        ),
        from_block_id=request.from_block_id,
        to_block_id=request.to_block_id,
        block_id=block_id,
        day_no=request.day_no,
    )


class FixedWindowRequiredError(PolicyRequiredError):
    """지정 시각이 없는 블록은 고정으로 바꿀 수 없다. API-007 은 시각을 받지 않으므로 고정 블록으로 다시 추가한다."""


def _day_of(schedule: ScheduleState, block_id: str) -> tuple[list[StoredBlock], int]:
    """편집할 블록이 있는 날의 블록(seq 순)과 그 안의 위치(0부터)."""
    block = next((b for b in schedule.blocks if b.id == block_id), None)
    if block is None:
        raise EngineInputError("Block does not exist")
    day = [b for b in schedule.blocks if b.day_no == block.day_no]
    if [b.seq for b in day] != list(range(1, len(day) + 1)):
        raise SequenceNormalizationRequiredError("Explicit legacy sequence migration is required")
    return day, block.seq - 1


def _starting_at(block: StoredBlock, arrive: time | None) -> StoredBlock:
    """재계산 시작점이 될 일반 블록의 시각. 엔진처럼 자정을 넘기면 출발 시각을 비운다."""
    depart = None
    if arrive is not None and minutes(arrive) + block.stay_min < 24 * 60:
        end = minutes(arrive) + block.stay_min
        depart = time(end // 60, end % 60)
    return block.model_copy(update={"arrive_at": arrive, "depart_at": depart})


def _edited(
    trip: TripWindow,
    schedule: ScheduleState,
    day_no: int,
    day: list[StoredBlock],
    start: int,
    day_start: time | None,
) -> RecomputeInput | ValidateInput:
    """편집한 날의 새 블록 순서(`day`)로 상태를 만들고 재계산 시작점을 고른다.

    `start` 는 바뀔 수 있는 첫 위치(0부터)다. 바로 앞 블록이 시작점이 되어 그 앞은 그대로 두고 뒤만 다시 계산한다.
    그날 첫 위치가 바뀌면(start=0) 새 첫 블록이 시작점이 되고, 일반 블록이면 그날 시작 시각(`day_start`)을 이어받는다.
    seq 는 1..n 으로 다시 매기고, 더 이상 이웃하지 않는 블록 사이의 구간은 버린다(엔진이 새 이웃 구간을 계산한다).
    그날 블록이 모두 없어지면 다시 계산할 것이 없으므로 `ValidateInput`(투영만)을 돌려준다.
    """
    day = [block.model_copy(update={"seq": seq}) for seq, block in enumerate(day, start=1)]
    if start == 0 and day and not day[0].is_fixed:
        day[0] = _starting_at(day[0], day_start)
    blocks = tuple(sorted([*(b for b in schedule.blocks if b.day_no != day_no), *day], key=lambda b: (b.day_no, b.seq)))
    adjacent = {(a.id, b.id) for a, b in zip(blocks, blocks[1:], strict=False) if a.day_no == b.day_no}
    state = ScheduleState(
        blocks=blocks,
        legs=tuple(leg for leg in schedule.legs if (leg.from_block_id, leg.to_block_id) in adjacent),
    )
    if not day:
        return ValidateInput(trip=trip, schedule=state)
    return RecomputeInput(trip=trip, schedule=state, from_block_id=day[max(start - 1, 0)].id)


def update_command(
    request: UpdateBlockRequest, trip: TripWindow, schedule: ScheduleState, block_id: str
) -> RecomputeInput | ValidateInput:
    """API-007 편집을 엔진 재계산 명령으로 바꾼다. 값이 그대로인 편집은 `ValidateInput`(투영만)이다.

    - seq: 같은 날 안에서만 옮기며 min(이전, 새 위치)부터 다시 계산한다.
    - stayMin: 이 블록부터 다시 계산한다(앞 블록이 시작점이므로 이 블록의 출발 시각도 바뀐다).
    - isFixed=true: 지정 시각이 없으면 `FixedWindowRequiredError`.
    - isFixed=false: 지정 시각을 지우고(mock 과 같음) 도착 시각은 그대로 둔 채 이 블록 뒤를 다시 계산한다.
    """
    day, index = _day_of(schedule, block_id)
    block, day_no, day_start = day[index], day[index].day_no, day[0].arrive_at
    if request.seq is not None:
        if request.seq > len(day):
            raise EngineInputError("Sequence is outside the day")
        if request.seq - 1 == index:
            return ValidateInput(trip=trip, schedule=schedule)
        day.insert(request.seq - 1, day.pop(index))
        return _edited(trip, schedule, day_no, day, min(index, request.seq - 1), day_start)
    if request.stay_min is not None:
        if request.stay_min == block.stay_min:
            return ValidateInput(trip=trip, schedule=schedule)
        day[index] = block.model_copy(update={"stay_min": request.stay_min})
        return _edited(trip, schedule, day_no, day, index, day_start)
    if request.is_fixed == block.is_fixed:
        return ValidateInput(trip=trip, schedule=schedule)
    if request.is_fixed:
        if block.fixed_start is None or block.fixed_end is None:
            raise FixedWindowRequiredError("Fixing a block needs an explicit fixed window")
        day[index] = block.model_copy(
            update={"is_fixed": True, "arrive_at": block.fixed_start, "depart_at": block.fixed_end}
        )
        return _edited(trip, schedule, day_no, day, index, day_start)
    released = block.model_copy(update={"is_fixed": False, "fixed_start": None, "fixed_end": None})
    day[index] = _starting_at(released, block.arrive_at)
    return _edited(trip, schedule, day_no, day, index + 1, day_start)


def delete_command(trip: TripWindow, schedule: ScheduleState, block_id: str) -> RecomputeInput | ValidateInput:
    """API-008. 뒤 블록 seq 를 1씩 당기고 같은 날 앞 블록부터 다시 계산한다.

    그날 첫 블록을 지우면 다음 블록이 그날 시작 시각을 이어받고(고정이면 그대로), 유일한 블록이면 투영만 한다.
    """
    day, index = _day_of(schedule, block_id)
    day_no, day_start = day[index].day_no, day[0].arrive_at
    del day[index]
    return _edited(trip, schedule, day_no, day, index, day_start)
