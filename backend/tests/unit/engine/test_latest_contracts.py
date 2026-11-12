from datetime import date, time
from math import nan

import pytest
from pydantic import ValidationError

from app.modules.engine.schemas import CalculationContext
from app.modules.trips.schemas import (
    AddBlockRequest,
    Block,
    GenerateScheduleRequest,
    KakaoBlockPlace,
    PlaceSummary,
    Schedule,
    ScheduleDay,
    SuggestWaypointsRequest,
    SuggestWaypointsResponse,
    WaypointCandidate,
)


def _public_place() -> PlaceSummary:
    return PlaceSummary(
        id="public-1",
        name="합성 공공 장소",
        lat=35.1,
        lng=129.1,
        category="museum",
        source="PUBLIC",
        ref_date=date(2026, 11, 2),
    )


def test_api_006_accepts_public_place_and_paired_slot() -> None:
    request = AddBlockRequest.model_validate(
        {
            "place": {"placeId": "public-1"},
            "isFixed": False,
            "origin": "SUGGESTED",
            "fromBlockId": "before",
            "toBlockId": "after",
        }
    )

    assert request.place.place_id == "public-1"
    assert request.from_block_id == "before"
    assert request.to_block_id == "after"


def test_api_006_accepts_kakao_id_and_place_url_only() -> None:
    request = AddBlockRequest.model_validate(
        {
            "place": {
                "kakaoPlaceId": "21362956",
                "placeUrl": "https://place.map.kakao.com/21362956",
            },
            "isFixed": True,
            "fixedWindow": {"dayNo": 1, "start": "10:00", "end": "11:00"},
            "origin": "USER",
        }
    )

    assert request.place.kakao_place_id == "21362956"
    assert request.model_dump(mode="json", by_alias=True)["place"] == {
        "kakaoPlaceId": "21362956",
        "placeUrl": "https://place.map.kakao.com/21362956",
    }


def test_api_006_rejects_old_url_field_and_kakao_search_data() -> None:
    with pytest.raises(ValidationError):
        AddBlockRequest.model_validate(
            {
                "place": {
                    "kakaoPlaceId": "21362956",
                    "kakaoPlaceUrl": "https://place.map.kakao.com/21362956",
                    "name": "저장 금지 이름",
                    "coords": {"lat": 35.1, "lng": 129.1},
                },
                "isFixed": False,
                "origin": "USER",
            }
        )


@pytest.mark.parametrize(
    "slot",
    [
        {"fromBlockId": "before"},
        {"toBlockId": "after"},
        {"fromBlockId": "same", "toBlockId": "same"},
    ],
)
def test_api_006_rejects_malformed_insertion_slot(slot: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        AddBlockRequest.model_validate(
            {
                "place": {"placeId": "public-1"},
                "isFixed": False,
                "origin": "USER",
                **slot,
            }
        )


@pytest.mark.parametrize("request_type", [GenerateScheduleRequest, SuggestWaypointsRequest])
def test_session_coords_are_request_only_and_transfer_to_calculation_context(request_type: type) -> None:
    payload: dict[str, object] = {
        "sessionCoords": {"21362956": {"lat": 35.1, "lng": 129.1}},
    }
    if request_type is SuggestWaypointsRequest:
        payload.update({"fromBlockId": "before", "toBlockId": "after", "thresholdMin": 15})

    request = request_type.model_validate(payload)
    context = CalculationContext(session_coords=request.session_coords)

    assert context.session_coords["21362956"].lat == 35.1
    assert "21362956" not in repr(request)
    assert "35.1" not in repr(context)
    assert "sessionCoords" not in request.model_dump(mode="json", by_alias=True)
    assert context.model_dump(mode="json", by_alias=True) == {}


@pytest.mark.parametrize(
    "coords",
    [
        {"lat": 91, "lng": 129.1},
        {"lat": 35.1, "lng": 181},
        {"lat": nan, "lng": 129.1},
        {"lat": 35.1, "lng": 129.1, "name": "저장 금지 이름"},
    ],
)
def test_session_coords_reject_invalid_or_extra_search_data(coords: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GenerateScheduleRequest.model_validate({"sessionCoords": {"21362956": coords}})


def test_api_009_serializes_kakao_block_with_id_url_and_source_only() -> None:
    block = Block(
        id="block-1",
        day_no=1,
        seq=0,
        place=KakaoBlockPlace(
            kakao_place_id="21362956",
            place_url="https://place.map.kakao.com/21362956",
        ),
        is_fixed=True,
        fixed_start=time(10),
        fixed_end=time(11),
        stay_min=60,
        arrive_at=time(10),
        depart_at=time(11),
        origin="USER",
    )
    schedule = Schedule(days=(ScheduleDay(day_no=1, date=date(2026, 11, 2), blocks=(block,)),))

    place = schedule.model_dump(mode="json", by_alias=True)["days"][0]["blocks"][0]["place"]
    assert place == {
        "kakaoPlaceId": "21362956",
        "placeUrl": "https://place.map.kakao.com/21362956",
        "source": "KAKAO",
    }


def test_api_009_public_block_shape_is_unchanged_and_user_selected_is_rejected() -> None:
    public = _public_place()
    dumped = public.model_dump(mode="json", by_alias=True)
    assert dumped["source"] == "PUBLIC"
    assert dumped["id"] == "public-1"
    assert dumped["name"] == "합성 공공 장소"

    with pytest.raises(ValidationError):
        PlaceSummary.model_validate({**dumped, "source": "USER_SELECTED"})


def test_api_011_limits_candidates_to_three_public_places() -> None:
    candidate = WaypointCandidate(
        place=_public_place(),
        detour_min=10,
        stay_min=30,
        crowd=None,
        reason="합성 이유",
    )
    response = SuggestWaypointsResponse(candidates=(candidate, candidate, candidate))
    assert len(response.candidates) == 3

    with pytest.raises(ValidationError):
        SuggestWaypointsResponse(candidates=(candidate, candidate, candidate, candidate))
