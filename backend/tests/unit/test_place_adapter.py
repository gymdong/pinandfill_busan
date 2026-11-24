"""FR-016과 기존 장소 데이터의 연동 테스트."""

from app.batch.jobs.place_adapter import to_existing_place
from app.batch.jobs.public_places import PublicPlaceRecord
from app.modules.places.samples import load_sample_places
from app.modules.places.schemas import PublicPlace


def test_existing_place_integration():
    samples = load_sample_places()
    existing = samples.place("1997221")
    assert existing is not None

    record = PublicPlaceRecord(
        content_id="1997221",
        name="감천문화마을",
        latitude=35.0974607,
        longitude=129.010597,
        address="부산광역시 사하구 감내2로",
    )
    result = to_existing_place(record, samples)

    assert isinstance(result, PublicPlace)
    assert result.id == existing.place.id
    assert result.category == existing.place.category
    assert result.hours == existing.place.hours
    assert result.lat == record.latitude
    assert result.lng == record.longitude


def test_unknown_place_is_not_inserted():
    samples = load_sample_places()
    record = PublicPlaceRecord(
        content_id="999999999999",
        name="미등록 장소",
        latitude=35.0,
        longitude=129.0,
        address="부산광역시",
    )
    assert to_existing_place(record, samples) is None
