"""FR-012 사진으로 장소 찾기(API-017): 공공 장소에서만 최대 3곳, 확신이 낮으면 찾지 못함, 형식·크기 오류는 ERR-014.

분류기는 가짜다(외부 API 를 부르지 않는다).
"""

import asyncio
import json
from collections.abc import Iterator, Sequence

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.photo import router as photo_router
from app.modules.photo.service import (
    ClaudePhotoClassifier,
    Guess,
    InvalidPhotoError,
    PhotoSearchService,
    PhotoUnavailableError,
)
from app.modules.photo.settings import PhotoSettings
from app.modules.places.samples import SamplePlace, load_sample_places

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def _reset_rate_limit() -> Iterator[None]:
    photo_router._recent.clear()
    yield
    photo_router._recent.clear()


class FakeClassifier:
    def __init__(self, guesses: list[Guess] | Exception) -> None:
        self.guesses = guesses
        self.calls: list[tuple[int, str, int]] = []

    async def classify(self, image: bytes, media_type: str, places: Sequence[SamplePlace]) -> list[Guess]:
        self.calls.append((len(image), media_type, len(places)))
        if isinstance(self.guesses, Exception):
            raise self.guesses
        return self.guesses


def _client(classifier: FakeClassifier, **settings: object) -> TestClient:
    places = load_sample_places()
    config = PhotoSettings(api_key=None, **settings)  # type: ignore[arg-type]
    service = PhotoSearchService(list(places.all()), classifier, config)
    return TestClient(create_app(photo_service=service))


def _post(client: TestClient, data: bytes = PNG, media_type: str = "image/png"):
    return client.post("/api/places/photo-search", files={"image": ("photo.png", data, media_type)})


def test_returns_up_to_three_public_places_by_confidence() -> None:
    guesses = [
        Guess("126078", 0.4),
        Guess("126658", 0.9),
        Guess("999999", 0.99),  # 목록에 없는 장소는 버린다
        Guess("126121", 0.35),
        Guess("130166", 0.5),
        Guess("126848", 1.5),  # 범위 밖 확신도는 버린다
    ]
    classifier = FakeClassifier(guesses)
    with _client(classifier) as client:
        response = _post(client)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["notFound"] is False
    assert [(c["place"]["id"], c["confidence"]) for c in body["candidates"]] == [
        ("126658", 0.9),
        ("130166", 0.5),
        ("126078", 0.4),
    ]
    assert body["candidates"][0]["place"]["name"] == "태종대유원지"
    assert classifier.calls == [(len(PNG), "image/png", len(load_sample_places().all()))]


def test_low_confidence_is_not_found() -> None:
    with _client(FakeClassifier([Guess("126658", 0.55)])) as client:
        body = _post(client).json()
    assert body == {"candidates": [], "notFound": True}
    with _client(FakeClassifier([])) as client:
        assert _post(client).json()["notFound"] is True


def test_invalid_photos_are_rejected_without_calling_the_model() -> None:
    classifier = FakeClassifier([])
    with _client(classifier, max_bytes=100) as client:
        wrong_type = _post(client, media_type="application/pdf")
        disguised = _post(client, data=b"%PDF-1.7" + b"0" * 40)  # image/png 라고 보냈지만 PDF
        too_large = _post(client, data=b"x" * 101)
        empty = _post(client, data=b"")
        missing = client.post("/api/places/photo-search")
    assert wrong_type.status_code == 400 and wrong_type.json()["error"]["id"] == "ERR-014"
    assert too_large.status_code == 413 and too_large.json()["error"]["id"] == "ERR-014"
    assert disguised.status_code == 400
    assert empty.status_code == 400
    assert missing.status_code == 400 and missing.json()["error"]["id"] == "ERR-014"
    assert classifier.calls == []


def test_provider_failure_is_503_and_missing_key_disables_the_endpoint(monkeypatch) -> None:
    with _client(FakeClassifier(PhotoUnavailableError("timeout"))) as client:
        failed = _post(client)
    assert failed.status_code == 503 and "이름으로 검색" in failed.json()["error"]["message"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(
        "app.modules.photo.settings.PhotoSettings.model_config", {**PhotoSettings.model_config, "env_file": None}
    )
    with TestClient(create_app()) as client:
        disabled = _post(client)
    assert disabled.status_code == 503


def test_rate_limit_per_client() -> None:
    with _client(FakeClassifier([]), per_minute=2) as client:
        codes = [_post(client).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def _claude(handler) -> ClaudePhotoClassifier:  # type: ignore[no-untyped-def]
    classifier = ClaudePhotoClassifier(PhotoSettings(api_key=None), "test-key")
    classifier.client = classifier.client.with_options(
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)), max_retries=0
    )
    return classifier


def _message(text: str | None, stop_reason: str = "end_turn") -> dict[str, object]:
    content = [] if text is None else [{"type": "text", "text": text}]
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _run(classifier: ClaudePhotoClassifier) -> list[Guess]:
    places = list(load_sample_places().all())
    return asyncio.run(classifier.classify(PNG, "image/png", places))


def test_claude_classifier_parses_structured_output_and_sends_enum() -> None:
    sent: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, json=_message('{"candidates": [{"place_id": "126658", "confidence": 0.8}]}'))

    assert _run(_claude(handler)) == [Guess("126658", 0.8)]
    body = sent[0]
    schema = body["output_config"]["format"]["schema"]  # type: ignore[index]
    assert "126658" in schema["properties"]["candidates"]["items"]["properties"]["place_id"]["enum"]
    assert body["fallbacks"] == "default" and body["model"] == "claude-opus-5-5"


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx2.Response(200, json=_message(None, "refusal")), PhotoUnavailableError),
        (httpx2.Response(200, json=_message("{", "max_tokens")), PhotoUnavailableError),
        (httpx2.Response(200, json=_message("not json")), PhotoUnavailableError),
        (
            httpx2.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "x"}}),
            PhotoUnavailableError,
        ),
        (
            httpx2.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "x"}}),
            InvalidPhotoError,
        ),
    ],
)
def test_claude_classifier_maps_failures(response: httpx2.Response, error: type[Exception]) -> None:
    with pytest.raises(error):
        _run(_claude(lambda request: response))
