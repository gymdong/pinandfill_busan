"""Translate HTTP contracts without retaining request-only Kakao coordinates."""

from app.modules.engine.schemas import (
    BlockDraft,
    CalculationContext,
    InsertInput,
    KakaoPlaceRef,
    PublicPlaceRef,
    ScheduleState,
    TripWindow,
)
from app.modules.trips.schemas import AddBlockRequest, PublicPlaceInput, WithSessionCoords


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
    )
