"""FR-016 TourAPI 클라이언트 단위 테스트."""

import httpx
import pytest

from app.batch.jobs.tourapi_client import (
    TOURAPI_DETAIL_URL,
    TourAPIError,
    TourAPIRejectedError,
    TourAPITransportError,
    fetch_public_place,
)


def sample_payload(content_id="1997221"):
    return {
        "response": {
            "body": {
                "items": {
                    "item": {
                        "contentid": content_id,
                        "title": "감천문화마을",
                        "addr1": "부산광역시 사하구 감내2로",
                        "mapy": "35.0974607",
                        "mapx": "129.010597",
                    }
                }
            }
        }
    }


def make_client(payload=None, status_code=200):
    def handler(request):
        return httpx.Response(
            status_code,
            json=payload if payload is not None else sample_payload(),
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_valid_public_place():
    with make_client() as client:
        record = fetch_public_place("1997221", api_key="test-key", client=client)

    assert record.content_id == "1997221"
    assert record.name == "감천문화마을"
    assert record.latitude == 35.0974607


def test_request_parameters():
    captured = {}

    def handler(request):
        captured["url"] = request.url
        return httpx.Response(200, json=sample_payload())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetch_public_place("1997221", api_key="test-key", client=client)

    assert captured["url"].path == httpx.URL(TOURAPI_DETAIL_URL).path
    assert captured["url"].params["contentId"] == "1997221"
    assert captured["url"].params["serviceKey"] == "test-key"


def test_invalid_content_id():
    with pytest.raises(ValueError):
        fetch_public_place("invalid", api_key="test-key")


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("TOURAPI_SERVICE_KEY", raising=False)

    with pytest.raises(TourAPIError, match="설정되지"):
        fetch_public_place("1997221")


def test_empty_item_is_rejected():
    with make_client(payload={"response": {"body": {"items": {"item": []}}}}) as client:
        with pytest.raises(TourAPIRejectedError):
            fetch_public_place("1997221", api_key="test-key", client=client)


def test_http_error():
    with make_client(status_code=500) as client:
        with pytest.raises(TourAPITransportError):
            fetch_public_place("1997221", api_key="test-key", client=client)


def test_invalid_response():
    with make_client(payload={"invalid": True}) as client:
        with pytest.raises(TourAPIError):
            fetch_public_place("1997221", api_key="test-key", client=client)


def test_mismatched_content_id():
    with make_client(payload=sample_payload("999999")) as client:
        with pytest.raises(TourAPIRejectedError):
            fetch_public_place("1997221", api_key="test-key", client=client)


def test_network_error():
    def handler(request):
        raise httpx.ConnectError("Connection failed", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TourAPIError):
            fetch_public_place("1997221", api_key="test-key", client=client)


def test_http_error_does_not_expose_service_key():
    """HTTP 오류에서 인증키가 예외 메시지에 노출되지 않아야 한다."""
    import traceback

    secret = "SECRET_TEST_KEY_123456"

    with make_client(status_code=500) as client:
        with pytest.raises(TourAPIError) as error:
            fetch_public_place(
                "1997221",
                api_key=secret,
                client=client,
            )

    assert secret not in str(error.value)
    assert secret not in "".join(traceback.format_exception(error.value))


@pytest.mark.parametrize(
    "payload",
    [
        {"response": None},
        {"response": []},
        {"response": {"body": None}},
        {"response": {"body": []}},
        {"response": {"body": {"items": None}}},
        {"response": {"body": {"items": []}}},
    ],
)
def test_malformed_nested_response(payload):
    """잘못된 중첩 응답은 전송 오류(TourAPITransportError)로 처리한다."""
    with make_client(payload=payload) as client:
        with pytest.raises(TourAPITransportError):
            fetch_public_place(
                "1997221",
                api_key="test-key",
                client=client,
            )
