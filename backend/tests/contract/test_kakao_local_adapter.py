"""카카오 로컬 어댑터 계약 테스트. 실제 카카오를 호출하지 않고 공식 문서의 요청·응답 형식을 흉내 낸다."""

import json
import logging
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from app.adapters.kakao import KakaoLocalAdapter, KakaoLocalError, KakaoSettings

pytestmark = pytest.mark.anyio

FIXTURE = json.loads((Path(__file__).parents[1] / "fixtures" / "kakao" / "keyword_search.json").read_text("utf-8"))
URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
TEST_KEY = "test-rest-key"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def settings() -> KakaoSettings:
    return KakaoSettings(rest_api_key=TEST_KEY, _env_file=None)


@pytest.fixture
async def adapter(settings: KakaoSettings):
    async with httpx.AsyncClient() as client:
        yield KakaoLocalAdapter(client, settings)


async def test_request_follows_kakao_spec(adapter, settings, respx_mock):
    route = respx_mock.get(URL).respond(json=FIXTURE)

    await adapter.search_keyword("  예시  ")

    request = route.calls.last.request
    assert request.headers["Authorization"] == f"KakaoAK {TEST_KEY}"
    assert dict(request.url.params) == {"query": "예시", "size": "15", "rect": settings.search_rect}


async def test_category_group_code_is_passed(adapter, respx_mock):
    route = respx_mock.get(URL).respond(json=FIXTURE)

    await adapter.search_keyword("예시", category_group_code="CE7")

    assert route.calls.last.request.url.params["category_group_code"] == "CE7"


async def test_maps_documents_to_places(adapter, respx_mock):
    respx_mock.get(URL).respond(json=FIXTURE)

    places = await adapter.search_keyword("예시")

    first = places[0]
    assert first.kakao_place_id == "900000001"
    assert first.name == "예시해변공원"
    assert (first.lat, first.lng) == (35.15, 129.12)
    assert first.category_group_code == "AT4"
    assert first.address == "부산 수영구 예시동 1-1"
    assert first.place_url == "https://example.com/kakao-place/900000001"
    assert places[1].road_address == ""


async def test_keeps_only_busan_places(adapter, respx_mock):
    respx_mock.get(URL).respond(json=FIXTURE)

    places = await adapter.search_keyword("예시")

    assert [place.kakao_place_id for place in places] == ["900000001", "900000002"]


async def test_no_results(adapter, respx_mock):
    respx_mock.get(URL).respond(json={"meta": {"total_count": 0}, "documents": []})

    assert await adapter.search_keyword("없는곳") == []


async def test_calls_kakao_every_time_without_caching(adapter, respx_mock):
    route = respx_mock.get(URL).respond(json=FIXTURE)

    await adapter.search_keyword("예시")
    await adapter.search_keyword("예시")

    assert route.call_count == 2


async def test_blank_query_is_rejected_without_calling(adapter, respx_mock):
    route = respx_mock.get(URL).respond(json=FIXTURE)

    with pytest.raises(ValueError):
        await adapter.search_keyword("   ")

    assert route.call_count == 0


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (400, {"code": -10, "msg": "example"}, "quota_exceeded"),
        (400, {"code": -2, "msg": "example"}, "http_status"),
        (401, {"code": -401, "msg": "example"}, "auth"),
        (403, {"errorType": "Example", "message": "example"}, "auth"),
        (500, None, "http_status"),
        (503, None, "http_status"),
    ],
)
async def test_error_status_raises_with_reason(adapter, respx_mock, status, body, reason):
    respx_mock.get(URL).respond(status, json=body) if body else respx_mock.get(URL).respond(status, text="<html>")

    with pytest.raises(KakaoLocalError) as error:
        await adapter.search_keyword("예시")

    assert (error.value.reason, error.value.status_code) == (reason, status)


@pytest.mark.parametrize(
    ("side_effect", "reason"),
    [(httpx.ReadTimeout("timeout"), "timeout"), (httpx.ConnectError("refused"), "network")],
)
async def test_transport_failure_raises(adapter, respx_mock, side_effect, reason):
    respx_mock.get(URL).mock(side_effect=side_effect)

    with pytest.raises(KakaoLocalError) as error:
        await adapter.search_keyword("예시")

    assert (error.value.reason, error.value.status_code) == (reason, None)


@pytest.mark.parametrize("body", [b"<html>Bad Gateway</html>", b'{"meta": {}}', b'{"documents": "x"}', b"[]"])
async def test_unexpected_body_raises(adapter, respx_mock, body):
    respx_mock.get(URL).respond(content=body)

    with pytest.raises(KakaoLocalError) as error:
        await adapter.search_keyword("예시")

    assert error.value.reason == "invalid_response"


async def test_skips_malformed_documents(adapter, respx_mock, caplog):
    broken = [{"id": "1", "place_name": "좌표없음", "x": "", "y": "35.1", "place_url": "u"}, "문자열", {"id": "2"}]
    respx_mock.get(URL).respond(json={"documents": [*broken, FIXTURE["documents"][0]]})

    with caplog.at_level(logging.INFO, logger="app.adapters.kakao"):
        places = await adapter.search_keyword("예시")

    assert [place.kakao_place_id for place in places] == ["900000001"]
    assert "skipped=3" in caplog.text
    assert "좌표없음" not in caplog.text


async def test_region_filter_falls_back_to_road_address(adapter, respx_mock):
    document = {**FIXTURE["documents"][0], "address_name": "", "road_address_name": "부산 수영구 예시해변로 1"}
    outside = {**FIXTURE["documents"][2], "address_name": ""}
    respx_mock.get(URL).respond(json={"documents": [document, outside]})

    places = await adapter.search_keyword("예시")

    assert [place.kakao_place_id for place in places] == ["900000001"]


def _leaks(query: str) -> tuple[str, ...]:
    return (query, quote(query), TEST_KEY, "예시해변공원", "129.12", "900000001")


async def test_logs_only_status_duration_and_count(adapter, respx_mock, caplog):
    respx_mock.get(URL).respond(json=FIXTURE)

    # httpx 등 다른 라이브러리의 로그까지 모두 잡는다.
    with caplog.at_level(logging.DEBUG):
        await adapter.search_keyword("비밀검색어")

    assert "count=2" in caplog.text
    for leaked in _leaks("비밀검색어"):
        assert leaked not in caplog.text


@pytest.mark.parametrize(
    "mock",
    [
        {"side_effect": httpx.ConnectError("refused")},
        {"return_value": httpx.Response(500, text="비밀검색어")},
        {"return_value": httpx.Response(200, json={"documents": "예시해변공원"})},
    ],
)
async def test_failure_does_not_expose_query_key_or_response(adapter, respx_mock, caplog, mock):
    respx_mock.get(URL).mock(**mock)

    with caplog.at_level(logging.DEBUG), pytest.raises(KakaoLocalError) as error:
        await adapter.search_keyword("비밀검색어")

    # 원래 예외(요청 URL·응답 값 포함)가 연결되어 있지 않아야 한다.
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    for leaked in _leaks("비밀검색어"):
        assert leaked not in caplog.text
        assert leaked not in str(error.value)


def test_settings_read_prefixed_env_and_hide_key(monkeypatch):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "from-env")

    settings = KakaoSettings(_env_file=None)

    assert settings.rest_api_key.get_secret_value() == "from-env"
    assert "from-env" not in repr(settings)
