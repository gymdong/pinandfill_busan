"""FR-016 기존 장소 모델 연동 테스트.

실제 data/samples 파일을 사용하지 않는다.
"""

import csv

import pytest

from app.batch.jobs.place_adapter import to_existing_place
from app.batch.jobs.public_places import PublicPlaceRecord
from app.modules.places.samples import load_sample_places
from app.modules.places.schemas import PublicPlace


@pytest.fixture
def sample_data(tmp_path):
    """테스트 전용 관광지 데이터를 임시 디렉터리에 생성한다."""
    file_path = tmp_path / "places_sample.csv"

    with file_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "name",
                "address",
                "lat",
                "lng",
                "category",
                "tourapi_contentid",
                "checked_at",
                "default_stay_min",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "name": "감천문화마을",
                "address": "부산광역시 사하구 감내2로",
                "lat": "35.0974607",
                "lng": "129.010597",
                "category": "관광지",
                "tourapi_contentid": "1997221",
                "checked_at": "2026-11-25",
                "default_stay_min": "90",
            }
        )

    return load_sample_places(tmp_path)


def make_record(content_id="1997221"):
    return PublicPlaceRecord(
        content_id=content_id,
        name="감천문화마을",
        latitude=35.0974607,
        longitude=129.010597,
        address="부산광역시 사하구 감내2로",
    )


def test_existing_place_integration(sample_data):
    existing = sample_data.place("1997221")
    assert existing is not None

    record = make_record()
    result = to_existing_place(record, sample_data)

    assert isinstance(result, PublicPlace)
    assert result.id == existing.place.id
    assert result.name == record.name
    assert result.lat == record.latitude
    assert result.lng == record.longitude
    assert result.category == existing.place.category
    assert result.hours == existing.place.hours


def test_unknown_place_is_not_inserted(sample_data):
    record = make_record("999999999999")

    result = to_existing_place(record, sample_data)

    assert result is None
