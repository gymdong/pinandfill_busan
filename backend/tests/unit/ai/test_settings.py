"""GEMINI_* 설정을 읽는 규칙: 잘못된 값은 예외 대신 LLM 을 끈다(AI-REQ-05). 값은 로그에 남기지 않는다."""

import logging

import pytest

from app.modules.ai.interpret import build_interpret_service
from app.modules.ai.settings import AISettings, default_ai_settings, load_ai_settings
from app.modules.recommend.mood import build_mood_service
from app.modules.recommend.mood_data import StaticMoodData

SECRET = "synthetic-gemini-key-value"


@pytest.fixture
def no_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """개발자 PC 의 backend/.env 를 읽지 않게 한다. 환경변수만으로 확인한다."""
    monkeypatch.setitem(AISettings.model_config, "env_file", None)


@pytest.mark.usefixtures("no_env_file")
def test_default_timeout_waits_for_gemini_but_fits_screen_timeout():
    settings = AISettings()
    # 실제 응답(약 10초)보다 길고, 재시도까지 더해도 화면의 요청 제한(30초, 한 줄 해석·분위기 찾기) 안이다.
    assert settings.timeout_seconds > 10
    assert settings.timeout_seconds * settings.max_attempts < 30


@pytest.mark.usefixtures("no_env_file")
def test_valid_settings_are_loaded(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "7")
    settings = load_ai_settings("test")
    assert settings is not None
    assert settings.timeout_seconds == 7
    assert settings.api_key is not None and settings.api_key.get_secret_value() == SECRET


@pytest.mark.usefixtures("no_env_file")
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GEMINI_TIMEOUT_SECONDS", "abc"),
        ("GEMINI_TIMEOUT_SECONDS", "0"),
        ("GEMINI_MAX_ATTEMPTS", "9"),
        ("GEMINI_TEMPERATURE", "-1"),
        ("GEMINI_MAX_INPUT_CHARS", "x"),
    ],
)
def test_invalid_settings_return_none_and_log_only_the_field_name(monkeypatch, caplog, name, value):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.setenv(name, value)
    with caplog.at_level(logging.WARNING):
        assert load_ai_settings("ai_interpret") is None
    field = name.removeprefix("GEMINI_").lower()
    # 메시지 전체가 정해진 형식과 같으므로 잘못된 값은 들어 있지 않다. 키도 남지 않는다.
    assert caplog.messages == [f"ai_settings invalid component=ai_interpret fields={field} llm=disabled"]
    assert SECRET not in caplog.text


def test_default_settings_have_no_key_and_the_declared_defaults():
    settings = default_ai_settings()
    assert settings.api_key is None
    assert (settings.max_input_chars, settings.max_attempts) == (200, 2)


@pytest.mark.usefixtures("no_env_file")
def test_interpret_service_runs_rules_only_when_settings_are_invalid(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "abc")
    service = build_interpret_service()
    assert service._llm is None
    # 입력 길이 제한은 기본값(200자)으로 계속 지킨다.
    assert service._settings.max_input_chars == 200


@pytest.mark.usefixtures("no_env_file")
def test_mood_service_runs_rules_only_when_settings_are_invalid(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.setenv("GEMINI_MAX_ATTEMPTS", "abc")
    service = build_mood_service(StaticMoodData((), ()))
    assert service._llm is None
    assert service._settings.max_input_chars == 200


def test_explicit_settings_are_used_as_given():
    explicit = AISettings(_env_file=None, api_key=None, max_input_chars=50)
    assert build_interpret_service(explicit)._settings is explicit
