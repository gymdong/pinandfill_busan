"""FR-016 TourAPI 다건 수집 및 결과 집계 테스트."""

from unittest.mock import patch

from app.batch.jobs.public_places import PublicPlaceRecord
from app.batch.jobs.public_places_batch import collect_public_places
from app.batch.jobs.tourapi_client import TourAPIError


def sample_record(content_id: str) -> PublicPlaceRecord:
    return PublicPlaceRecord(
        content_id=content_id,
        name="부산 감천문화마을",
        address="부산광역시 사하구 감내2로",
        latitude=35.0974607,
        longitude=129.010597,
    )


def test_successful_batch():
    with patch(
        "app.batch.jobs.public_places_batch.fetch_public_place",
        side_effect=[sample_record("1997221"), sample_record("126078")],
    ) as mock_fetch:
        result = collect_public_places(["1997221", "126078"])

    assert result.success_count == 2
    assert result.failed_count == 0
    assert len(result.records) == 2
    assert mock_fetch.call_count == 2


def test_failed_batch():
    with patch(
        "app.batch.jobs.public_places_batch.fetch_public_place",
        side_effect=[
            sample_record("1997221"),
            TourAPIError("API 오류"),
        ],
    ):
        result = collect_public_places(["1997221", "126078"])

    assert result.success_count == 1
    assert result.failed_count == 1


def test_duplicate_ids():
    with patch(
        "app.batch.jobs.public_places_batch.fetch_public_place",
        return_value=sample_record("1997221"),
    ) as mock_fetch:
        result = collect_public_places(["1997221", "1997221"])

    assert result.success_count == 1
    assert result.failed_count == 0
    assert mock_fetch.call_count == 1
