"""Translate the agreed initial-generation contract to the existing planner."""

from collections.abc import Callable
from datetime import date
from uuid import uuid4

from app.modules.engine.initial import InitialScheduleCommand, InitialSelection
from app.modules.engine.schemas import KakaoPlaceRef, PlaceRef, PublicPlaceRef, TripWindow
from app.modules.trips.schemas import InitialGenerationInput, KakaoPlaceKey, PublicPlaceInput


class PublicStayDurations:
    """Bridge the existing static public-place durations; no Kakao fallback or tag default.

    The sample provider has no date-dependent durations. A future DB provider
    can implement the planner's on_date-aware protocol directly.
    """

    def __init__(self, lookup: Callable[[PublicPlaceInput | KakaoPlaceKey], int | None]) -> None:
        self.lookup = lookup

    def get(self, place_ref: PlaceRef, *, on_date: date) -> int | None:
        if isinstance(place_ref, PublicPlaceRef):
            return self.lookup(PublicPlaceInput(place_id=place_ref.place_id))
        return None


def initial_command(request: InitialGenerationInput, trip: TripWindow) -> tuple[InitialScheduleCommand, dict[str, str]]:
    """Generate server IDs; the client mapping lives only for this calculation."""
    selections: list[InitialSelection] = []
    client_ids: dict[str, str] = {}
    for selected in request.selections:
        block_id = str(uuid4())
        client_ids[block_id] = selected.client_id
        place_ref: PlaceRef
        if isinstance(selected.place, PublicPlaceInput):
            place_ref = PublicPlaceRef(place_id=selected.place.place_id)
        else:
            place_ref = KakaoPlaceRef(kakao_place_id=selected.place.kakao_place_id, placeUrl=selected.place.place_url)
        selections.append(
            InitialSelection(
                block_id=block_id,
                place_ref=place_ref,
                stay_min=selected.stay_min,
                fixed_window=selected.fixed_window,
                allowed_days=(selected.day_no,) if selected.day_no is not None else None,
            )
        )
    return InitialScheduleCommand(trip=trip, selections=tuple(selections), policy=request.policy), client_ids
