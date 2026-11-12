from datetime import date, time

from app.modules.engine.schemas import KakaoPlaceRef, ScheduleState, TripWindow
from app.modules.trips.commands import calculation_context, insert_command
from app.modules.trips.schemas import AddBlockRequest


def test_wire_request_splits_into_coordinate_free_command_and_ephemeral_context() -> None:
    request = AddBlockRequest.model_validate(
        {
            "place": {"kakaoPlaceId": "123", "placeUrl": "https://place.map.kakao.com/123"},
            "isFixed": False,
            "origin": "USER",
            "fromBlockId": "a",
            "toBlockId": "b",
            "sessionCoords": {"123": {"lat": 35.123456, "lng": 129.654321}},
        }
    )
    trip = TripWindow(
        start_date=date(2026, 11, 7),
        end_date=date(2026, 11, 7),
        day_start=time(9),
        day_end=time(18),
        transport_mode="WALK",
    )
    command = insert_command(request, trip, ScheduleState(), stay_min=40, block_id="new")
    context = calculation_context(request)
    assert isinstance(command.block.place_ref, KakaoPlaceRef)
    assert command.block.stay_min == 40
    assert command.from_block_id == "a"
    assert command.to_block_id == "b"
    assert context.session_coords["123"].lat == 35.123456
    # Context copies the mapping; it is not a global session store.
    request.session_coords.clear()
    assert "123" in context.session_coords
    assert "35.123456" not in command.model_dump_json()
    assert "129.654321" not in command.model_dump_json()
    assert context.model_dump() == {}
    assert "35.123456" not in repr(command)
