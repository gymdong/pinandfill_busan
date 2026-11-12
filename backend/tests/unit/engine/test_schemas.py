from datetime import UTC, date, datetime, time

import pytest
from pydantic import ValidationError

from app.modules.engine.schemas import (
    KakaoPlaceRef,
    PublicPlaceRef,
    ScheduleState,
    StoredBlock,
    StoredLeg,
    TransientPlaceDetails,
    TripWindow,
)
from app.modules.trips.schemas import Block, Leg, PlaceSummary, Schedule, ScheduleDay


def test_kakao_reference_rejects_search_payload() -> None:
    with pytest.raises(ValidationError) as error:
        KakaoPlaceRef.model_validate(
            {
                "kind": "KAKAO",
                "kakaoPlaceId": "123",
                "kakaoPlaceUrl": "https://place.map.kakao.com/123",
                "name": "저장하면 안 되는 이름",
                "lat": 35.1,
            }
        )
    assert "저장하면 안 되는 이름" not in str(error.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://place.map.kakao.com/123",
        "https://place.map.kakao.com/456",
        "https://place.map.kakao.com/123?name=secret",
        "https://place.map.kakao.com/123#secret",
    ],
)
def test_kakao_reference_accepts_only_matching_canonical_url(url: str) -> None:
    with pytest.raises(ValidationError):
        KakaoPlaceRef(kakao_place_id="123", kakao_place_url=url)


def test_persistent_state_contains_only_kakao_id_and_url() -> None:
    state = ScheduleState(
        blocks=(
            StoredBlock(
                id="block-1",
                day_no=1,
                seq=0,
                place_ref=KakaoPlaceRef(
                    kakao_place_id="123",
                    kakao_place_url="https://place.map.kakao.com/123",
                ),
                is_fixed=True,
                fixed_start=time(10),
                fixed_end=time(11),
                stay_min=60,
                arrive_at=time(10),
                depart_at=time(11),
                origin="USER",
            ),
        )
    )

    dumped = state.model_dump(mode="json", by_alias=True)
    ref = dumped["blocks"][0]["placeRef"]
    assert ref == {
        "kind": "KAKAO",
        "kakaoPlaceId": "123",
        "placeUrl": "https://place.map.kakao.com/123",
    }
    assert "name" not in str(dumped)
    assert "lat" not in str(dumped)

    with pytest.raises(ValidationError):
        state.blocks[0].stay_min = 30


def test_transient_details_do_not_serialize_or_repr_search_information() -> None:
    details = TransientPlaceDetails(
        place_ref=PublicPlaceRef(place_id="public-1"),
        name="임시 이름",
        lat=35.1,
        lng=129.1,
    )

    assert details.name == "임시 이름"
    assert details.model_dump(mode="json", by_alias=True) == {"placeRef": {"kind": "PUBLIC", "placeId": "public-1"}}
    assert "임시 이름" not in repr(details)
    assert "35.1" not in repr(details)


def test_api_009_schedule_uses_frontend_camel_case_shape() -> None:
    place = PlaceSummary(
        id="public-1",
        name="부산시립미술관",
        lat=35.171,
        lng=129.131,
        category="museum",
        source="PUBLIC",
        ref_date=date(2026, 10, 25),
    )
    block = Block(
        id="block-1",
        day_no=1,
        seq=0,
        place=place,
        is_fixed=True,
        fixed_start=time(10),
        fixed_end=time(11),
        stay_min=60,
        arrive_at=time(10),
        depart_at=time(11),
        origin="USER",
    )
    leg = Leg(
        id="leg-1",
        from_block_id="block-1",
        to_block_id="block-2",
        mode="TRANSIT",
        duration_min=20,
        computed_at=datetime(2026, 10, 25, tzinfo=UTC),
        source="ESTIMATED",
    )
    schedule = Schedule(
        days=(
            ScheduleDay(
                day_no=1,
                date=date(2026, 11, 10),
                blocks=(block,),
                legs=(leg,),
            ),
        )
    )

    body = schedule.model_dump(mode="json", by_alias=True)
    assert set(body) == {"days", "violations", "conflicts"}
    assert set(body["days"][0]) == {
        "dayNo",
        "date",
        "blocks",
        "legs",
        "crowd",
        "weather",
    }
    assert body["days"][0]["blocks"][0]["isFixed"] is True
    assert body["days"][0]["blocks"][0]["fixedStart"] == "10:00"
    assert body["days"][0]["legs"][0]["source"] == "ESTIMATED"


@pytest.mark.parametrize(
    "model, payload",
    [
        (
            PublicPlaceRef,
            {"kind": "KAKAO", "placeId": "public-1"},
        ),
        (
            TransientPlaceDetails,
            {
                "placeRef": {"kind": "PUBLIC", "placeId": "public-1"},
                "name": "범위 밖 좌표",
                "lat": 91,
                "lng": 129,
            },
        ),
        (
            StoredLeg,
            {
                "id": "leg-1",
                "fromBlockId": "a",
                "toBlockId": "b",
                "mode": "TRANSIT",
                "durationMin": -1,
                "source": "ESTIMATED",
            },
        ),
    ],
)
def test_models_reject_invalid_discriminator_coordinates_and_duration(model: type, payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_models_reject_negative_stay_and_second_precision() -> None:
    base = {
        "id": "block-1",
        "dayNo": 1,
        "seq": 0,
        "placeRef": {"kind": "PUBLIC", "placeId": "public-1"},
        "isFixed": True,
        "fixedStart": "10:00:01",
        "fixedEnd": "11:00",
        "stayMin": -1,
        "origin": "USER",
    }
    with pytest.raises(ValidationError) as error:
        StoredBlock.model_validate(base)

    error_types = {item["type"] for item in error.value.errors(include_input=False)}
    assert "greater_than" in error_types
    assert "value_error" in error_types


def test_trip_window_rejects_reversed_date_range() -> None:
    with pytest.raises(ValidationError):
        TripWindow(
            start_date=date(2026, 11, 3),
            end_date=date(2026, 11, 2),
            day_start=time(9),
            day_end=time(18),
            transport_mode="TRANSIT",
        )


def test_local_time_rejects_offset_instead_of_silently_dropping_it() -> None:
    with pytest.raises(ValidationError):
        TripWindow.model_validate(
            {
                "startDate": "2026-11-02",
                "endDate": "2026-11-02",
                "dayStart": "09:00+09:00",
                "dayEnd": "18:00",
                "transportMode": "WALK",
            }
        )
