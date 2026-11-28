"""FR-012 사진으로 장소 찾기(API-017): 공공 장소에서만 최대 3곳, 확신이 낮으면 찾지 못함, 형식·크기 오류는 ERR-014.

분류기는 가짜다(외부 API 를 부르지 않는다).
"""

from collections.abc import Sequence

from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.photo.service import Guess, PhotoSearchService, PhotoUnavailableError
from app.modules.photo.settings import PhotoSettings
from app.modules.places.samples import SamplePlace, load_sample_places

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


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
        too_large = _post(client, data=b"x" * 101)
        empty = _post(client, data=b"")
        missing = client.post("/api/places/photo-search")
    assert wrong_type.status_code == 400 and wrong_type.json()["error"]["id"] == "ERR-014"
    assert too_large.status_code == 413 and too_large.json()["error"]["id"] == "ERR-014"
    assert empty.status_code == 400
    assert missing.status_code == 400
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
