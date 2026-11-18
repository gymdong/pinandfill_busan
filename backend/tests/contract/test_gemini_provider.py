"""Gemini 어댑터 계약 테스트. 실제 Gemini 를 호출하지 않고 generateContent 의 요청·응답 형식을 흉내 낸다."""

import json
import logging

import httpx
import pytest

from app.modules.ai.providers.base import LlmError
from app.modules.ai.providers.gemini import GeminiProvider
from app.modules.ai.settings import AISettings

pytestmark = pytest.mark.anyio

TEST_KEY = "test-gemini-key"
URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"
SCHEMA: dict[str, object] = {"type": "OBJECT", "properties": {"mode": {"type": "STRING", "nullable": True}}}
SYSTEM = "지시문 예시"
USER = "<user_text>사용자 문장 예시</user_text>"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def settings() -> AISettings:
    return AISettings(_env_file=None, api_key=TEST_KEY)


@pytest.fixture
def provider(settings: AISettings) -> GeminiProvider:
    return GeminiProvider(settings)


def candidate(text: str) -> dict[str, object]:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}]}


async def call(provider: GeminiProvider) -> object:
    return await provider.generate_json(system=SYSTEM, user=USER, schema=SCHEMA)


async def test_request_follows_generate_content_spec(provider, settings, respx_mock):
    route = respx_mock.post(URL).respond(json=candidate('{"mode": "TRANSIT"}'))

    assert await call(provider) == {"mode": "TRANSIT"}

    request = route.calls.last.request
    # 키는 URL 이 아니라 헤더로 보낸다. URL 은 요청 로그에 남을 수 있다.
    assert request.headers["x-goog-api-key"] == TEST_KEY
    assert TEST_KEY not in str(request.url)
    assert request.url.query == b""
    body = json.loads(request.content)
    # 지시문과 사용자 입력을 서로 다른 자리에 싣는다(AI-REQ-07).
    assert body["systemInstruction"] == {"parts": [{"text": SYSTEM}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": USER}]}]
    assert body["generationConfig"] == {
        "temperature": 0.0,
        "maxOutputTokens": settings.max_output_tokens,
        "responseMimeType": "application/json",
        "responseSchema": SCHEMA,
    }
    assert route.calls.last.request.extensions["timeout"]["read"] == settings.timeout_seconds


async def test_model_and_base_url_come_from_settings(respx_mock):
    settings = AISettings(_env_file=None, api_key=TEST_KEY, model="other-model", base_url="https://llm.example.test")
    route = respx_mock.post("https://llm.example.test/v1beta/models/other-model:generateContent").respond(
        json=candidate("{}")
    )
    assert await call(GeminiProvider(settings)) == {}
    assert route.called


async def test_uses_an_injected_client(settings, respx_mock):
    respx_mock.post(URL).respond(json=candidate("[1, 2]"))
    async with httpx.AsyncClient() as client:
        assert await call(GeminiProvider(settings, client)) == [1, 2]
        assert not client.is_closed


async def test_text_split_over_several_parts_is_joined(provider, respx_mock):
    payload = {"candidates": [{"content": {"parts": [{"text": '{"mode": '}, {"text": '"CAR"}'}]}}]}
    respx_mock.post(URL).respond(json=payload)
    assert await call(provider) == {"mode": "CAR"}


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (429, "quota_exceeded"),
        (401, "auth"),
        (403, "auth"),
        (400, "http_status"),
        (404, "http_status"),
        (503, "http_status"),
    ],
)
async def test_http_errors_are_classified_without_reading_the_body(provider, respx_mock, status, reason):
    respx_mock.post(URL).respond(status, json={"error": {"message": f"key {TEST_KEY} rejected"}})
    with pytest.raises(LlmError) as raised:
        await call(provider)
    assert (raised.value.reason, raised.value.status_code) == (reason, status)
    assert TEST_KEY not in str(raised.value)
    # 원래 예외(요청 정보 포함)와 연결을 끊는다.
    assert raised.value.__cause__ is None and raised.value.__context__ is None


@pytest.mark.parametrize(
    ("error", "reason"),
    [(httpx.ReadTimeout("slow"), "timeout"), (httpx.ConnectError("down"), "network")],
)
async def test_transport_failures(provider, respx_mock, error, reason):
    respx_mock.post(URL).mock(side_effect=error)
    with pytest.raises(LlmError) as raised:
        await call(provider)
    assert (raised.value.reason, raised.value.status_code) == (reason, None)
    assert raised.value.__cause__ is None and raised.value.__context__ is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"candidates": []},
        {"candidates": [{"finishReason": "SAFETY"}]},
        {"candidates": [{"content": {"parts": []}}]},
        candidate("JSON 이 아닌 글"),
        candidate('{"mode": "TRANSIT"'),
        ["unexpected"],
    ],
)
async def test_unreadable_responses_are_invalid(provider, respx_mock, payload):
    respx_mock.post(URL).respond(json=payload)
    with pytest.raises(LlmError) as raised:
        await call(provider)
    assert raised.value.reason == "invalid_response"


async def test_non_json_body_is_invalid(provider, respx_mock):
    respx_mock.post(URL).respond(content=b"<html>gateway</html>")
    with pytest.raises(LlmError) as raised:
        await call(provider)
    assert raised.value.reason == "invalid_response"


async def test_logs_only_status_and_duration(provider, respx_mock, caplog):
    respx_mock.post(URL).respond(json=candidate('{"mode": "TRANSIT"}'))
    with caplog.at_level(logging.DEBUG):
        await call(provider)
    respx_mock.post(URL).respond(500)
    with caplog.at_level(logging.DEBUG), pytest.raises(LlmError):
        await call(provider)

    messages = " | ".join(caplog.messages)
    assert "gemini_generate status=200 duration_ms=" in messages
    assert "gemini_generate failed reason=http_status status=500" in messages
    for secret in (TEST_KEY, "사용자 문장", "지시문", "TRANSIT"):
        assert secret not in messages


def test_provider_requires_a_key():
    with pytest.raises(ValueError):
        GeminiProvider(AISettings(_env_file=None, api_key=None))
