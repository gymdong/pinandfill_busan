from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[3]


class AISettings(BaseSettings):
    """LLM(Gemini) 설정. 환경변수 `GEMINI_*` 또는 backend/.env 에서 읽는다.

    키가 없으면 LLM 을 부르지 않고 규칙 기반 해석만 쓴다(AI-REQ-05).
    core 의 ConfigService(app_config)가 생기면 키를 제외한 값은 그쪽으로 옮긴다.
    """

    model_config = SettingsConfigDict(env_prefix="GEMINI_", env_file=BACKEND_DIR / ".env", extra="ignore")

    api_key: SecretStr | None = None
    # SDD 7.2 의 gemini-2.5-flash-lite 는 신규 키에 더 이상 제공되지 않아(404) 같은 경량 계열의 후속 모델을 쓴다.
    # 모델이 바뀌면 환경변수 GEMINI_MODEL 로 교체한다.
    model: str = "gemini-3.5-flash-lite"
    base_url: str = "https://generativelanguage.googleapis.com"
    timeout_seconds: float = Field(default=5.0, gt=0)
    temperature: float = Field(default=0.0, ge=0, le=2)
    # NFR-005: 요청당 호출 횟수(재시도 포함)와 출력 토큰 상한
    max_attempts: int = Field(default=2, ge=1, le=3)
    max_output_tokens: int = Field(default=512, ge=16)
    # 사용자 입력 최대 길이(글자). 잠정값이며 프런트 한 줄 입력의 maxLength 와 같다.
    max_input_chars: int = Field(default=200, ge=1)

    @field_validator("api_key", mode="before")
    @classmethod
    def blank_key_is_no_key(cls, value: object) -> object:
        """`.env` 의 `GEMINI_API_KEY=`(빈 값)은 키가 없는 것으로 본다. 빈 키로 LLM 을 부르지 않는다."""
        if isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, SecretStr) and not value.get_secret_value().strip():
            return None
        return value
