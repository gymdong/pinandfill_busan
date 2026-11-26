"""FR-016 TourAPI 다건 수집 및 결과 집계 테스트."""

from unittest.mock import patch

import pytest

from app.batch.jobs.public_places import PublicPlaceRecord
from app.batch.jobs.public_places_batch import collect_public_places
from app.batch.jobs.tourapi_client import TourAPIError, TourAPIRejectedError, TourAPITransportError

FETCH = "app.batch.jobs.public_places_batch.fetch_public_place"


def sample_record(content_id: str) -> PublicPlaceRecord:
    return PublicPlaceRecord(
        content_id=content_id,
        name="부산 감천문화마을",
        address="부산광역시 사하구 감내2로",
        latitude=35.0974607,
        longitude=129.010597,
    )


def test_successful_batch():
    with patch(FETCH, side_effect=[sample_record("1997221"), sample_record("126078")]) as mock_fetch:
        result = collect_public_places(["1997221", "126078"], api_key="test-key")

    assert result.success_count == 2
    assert result.failed_count == 0
    assert result.call_count == 2
    assert len(result.records) == 2
    assert mock_fetch.call_count == 2


def test_failed_batch():
    with patch(FETCH, side_effect=[sample_record("1997221"), TourAPIError("API 오류")]):
        result = collect_public_places(["1997221", "126078"], api_key="test-key")

    assert result.success_count == 1
    assert result.failed_count == 1
    # 상위 클래스 오류는 전송 오류로 본다(쓰지 않는 쪽이 안전하다).
    assert (result.transport_failures, result.rejected) == (1, 0)
    assert result.error_message == "API 오류"


def test_rejected_items_are_skipped_and_counted():
    with patch(FETCH, side_effect=[TourAPIRejectedError("검증 실패"), sample_record("126078")]):
        result = collect_public_places(["1997221", "126078", "busan:1"], api_key="test-key")

    assert [record.content_id for record in result.records] == ["126078"]
    # 숫자가 아닌 ID 는 호출하지 않고 거절로 센다.
    assert (result.transport_failures, result.rejected, result.call_count) == (0, 2, 2)
    assert result.error_message is None


def test_transport_error_stops_remaining_calls():
    error = TourAPITransportError("TourAPI 요청 실패 (HTTP 500)")
    with patch(FETCH, side_effect=[error, sample_record("2")]) as fetch:
        result = collect_public_places(["1", "2", "3"], api_key="test-key")

    assert fetch.call_count == 1
    assert (result.transport_failures, result.call_count, result.records) == (1, 1, ())
    assert result.error_message == "TourAPI 요청 실패 (HTTP 500)"


def test_missing_key_makes_no_calls(monkeypatch):
    monkeypatch.delenv("TOURAPI_SERVICE_KEY", raising=False)
    with patch(FETCH) as fetch, pytest.raises(TourAPITransportError, match="설정되지"):
        collect_public_places(["1997221"])
    assert fetch.call_count == 0


def test_duplicate_ids():
    with patch(FETCH, return_value=sample_record("1997221")) as mock_fetch:
        result = collect_public_places(["1997221", "1997221"], api_key="test-key")

    assert result.success_count == 1
    assert result.failed_count == 0
    assert mock_fetch.call_count == 1
