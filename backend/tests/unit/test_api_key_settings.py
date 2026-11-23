"""외부 API 키 설정 규칙: 빈 값·공백뿐인 값은 키 없음, 그 외는 앞뒤 공백을 뗀 값. 외부를 부르지 않는다."""

import pytest
from pydantic import ValidationError

from app.adapters.kakao import KakaoSettings
from app.adapters.route.settings import ODsaySettings, TMAPSettings
from app.main import kakao_settings
from app.modules.ai.settings import AISettings

BLANKS = ["", "   ", "\t\n"]
OPTIONAL_KEY_SETTINGS = [AISettings, TMAPSettings, ODsaySettings]


@pytest.mark.parametrize("settings_class", OPTIONAL_KEY_SETTINGS)
@pytest.mark.parametrize("blank", BLANKS)
def test_blank_key_is_missing(settings_class, blank):
    assert settings_class(_env_file=None, api_key=blank).api_key is None


@pytest.mark.parametrize("settings_class", OPTIONAL_KEY_SETTINGS)
def test_key_is_stripped(settings_class):
    assert settings_class(_env_file=None, api_key="  abc  ").api_key.get_secret_value() == "abc"


@pytest.mark.parametrize("blank", BLANKS)
def test_blank_kakao_key_fails_settings_and_disables_search(blank, monkeypatch):
    with pytest.raises(ValidationError) as error:
        KakaoSettings(_env_file=None, rest_api_key=blank)
    assert [item["loc"] for item in error.value.errors()] == [("rest_api_key",)]
    monkeypatch.setenv("KAKAO_REST_API_KEY", blank)
    assert kakao_settings() is None


def test_kakao_key_is_stripped(monkeypatch):
    assert KakaoSettings(_env_file=None, rest_api_key="  abc  ").rest_api_key.get_secret_value() == "abc"
    monkeypatch.setenv("KAKAO_REST_API_KEY", "  abc  ")
    settings = kakao_settings()
    assert settings is not None and settings.rest_api_key.get_secret_value() == "abc"


def test_blank_kakao_key_does_not_hide_other_invalid_settings(monkeypatch):
    monkeypatch.setenv("KAKAO_REST_API_KEY", "   ")
    monkeypatch.setenv("KAKAO_SEARCH_RECT", "bad")
    with pytest.raises(ValidationError):
        kakao_settings()
