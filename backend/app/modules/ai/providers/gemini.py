"""Gemini generateContent REST 어댑터. 응답을 저장·캐시하지 않고 프롬프트를 로그에 남기지 않는다."""

import json
import logging
import time

import httpx

from ..settings import AISettings
from .base import LlmError

logger = logging.getLogger(__name__)


class GeminiProvider:
    """LlmProvider 의 Gemini 구현(SDD 7.2).

    로그와 예외에는 상태·소요시간만 담고 프롬프트·응답·키는 담지 않는다(AI-REQ-07, NFR-010).
    키는 URL 이 아니라 헤더로 보내 요청 로그에 남지 않게 한다.
    """

    def __init__(self, settings: AISettings, client: httpx.AsyncClient | None = None) -> None:
        if settings.api_key is None:
            raise ValueError("GEMINI_API_KEY 가 없다")
        self._settings = settings
        self._api_key = settings.api_key.get_secret_value()
        # 주입한 클라이언트가 없으면 호출마다 만들고 닫는다.
        self._client = client

    @property
    def url(self) -> str:
        return f"{self._settings.base_url}/v1beta/models/{self._settings.model}:generateContent"

    async def generate_json(self, *, system: str, user: str, schema: dict[str, object]) -> object:
        settings = self._settings
        body: dict[str, object] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": settings.temperature,
                "maxOutputTokens": settings.max_output_tokens,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        started = time.perf_counter()
        # 원래 예외에는 요청 정보가 담길 수 있으므로 except 밖에서 새 예외를 던져 연결을 끊는다.
        response: httpx.Response | None = None
        transport_failure = ""
        try:
            response = await self._post(body)
        except httpx.TimeoutException:
            transport_failure = "timeout"
        except httpx.HTTPError:
            transport_failure = "network"
        if response is None:
            raise self._failure(transport_failure, started)

        if response.status_code != httpx.codes.OK:
            raise self._failure(_error_reason(response.status_code), started, response.status_code)

        parsed = _parse(response)
        if parsed is _INVALID:
            raise self._failure("invalid_response", started, response.status_code)
        logger.info("gemini_generate status=200 duration_ms=%d", _elapsed_ms(started))
        return parsed

    async def _post(self, body: dict[str, object]) -> httpx.Response:
        headers = {"x-goog-api-key": self._api_key}
        timeout = self._settings.timeout_seconds
        if self._client is not None:
            return await self._client.post(self.url, json=body, headers=headers, timeout=timeout)
        async with httpx.AsyncClient() as client:
            return await client.post(self.url, json=body, headers=headers, timeout=timeout)

    def _failure(self, reason: str, started: float, status_code: int | None = None) -> LlmError:
        logger.warning(
            "gemini_generate failed reason=%s status=%s duration_ms=%d", reason, status_code, _elapsed_ms(started)
        )
        return LlmError(reason, status_code)


_INVALID = object()


def _parse(response: httpx.Response) -> object:
    """첫 후보의 텍스트를 JSON 으로 읽는다. 형식이 다르면 `_INVALID`"""
    try:
        payload = json.loads(response.content)
        parts = payload["candidates"][0]["content"]["parts"]
        text = "".join(part["text"] for part in parts if isinstance(part, dict) and "text" in part)
        return json.loads(text)
    except (ValueError, KeyError, IndexError, TypeError):
        return _INVALID


def _error_reason(status_code: int) -> str:
    if status_code == httpx.codes.TOO_MANY_REQUESTS:
        return "quota_exceeded"
    if status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
        return "auth"
    return "http_status"


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
