import logging
from pathlib import Path

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.secrets import blank_key_is_no_key

BACKEND_DIR = Path(__file__).resolve().parents[3]

logger = logging.getLogger(__name__)


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
    # 호출 한 번의 시간 제한(초). 2026-11-21 P0 검증 때 실제 키로 잰 한 줄 해석 응답이 약 10초까지 걸려
    # 5초에서 시간 초과가 났다(2026-11-25 재측정은 1.6초). 느린 응답을 위한 여유값이다.
    # 재시도는 대기 없이 바로 다시 부르므로 최악은 12초 × max_attempts(2) = 24초다. 화면의 요청 제한
    # (frontend `pages/trip-start` 한 줄 해석·`pages/mood-search` 분위기 해석의 `timeoutMs: 30_000`) 안이어야 한다.
    timeout_seconds: float = Field(default=12.0, gt=0)
    temperature: float = Field(default=0.0, ge=0, le=2)
    # NFR-005: 요청당 호출 횟수(재시도 포함)와 출력 토큰 상한
    max_attempts: int = Field(default=2, ge=1, le=3)
    max_output_tokens: int = Field(default=512, ge=16)
    # 사용자 입력 최대 길이(글자). 잠정값이며 프런트 한 줄 입력의 maxLength 와 같다.
    max_input_chars: int = Field(default=200, ge=1)
    # 경유지 추천 이유 문구(API-011)에 LLM 을 기다리는 총시간(초, 재시도 포함). 넘으면 규칙 문구로 응답한다(ERR-002).
    # 잠정값: 후보 계산이 끝난 뒤 더해지는 지연이라 짧게 둔다.
    explain_budget_seconds: float = Field(default=4.0, gt=0)

    # `.env` 의 `GEMINI_API_KEY=`(빈 값)은 키가 없는 것으로 본다. 빈 키로 LLM 을 부르지 않는다.
    _normalize_key = field_validator("api_key", mode="before")(blank_key_is_no_key)


def load_ai_settings(component: str) -> AISettings | None:
    """환경 설정(GEMINI_*·backend/.env)을 읽는다. 값이 잘못됐으면 예외 대신 None 이다.

    LLM 은 부가 기능이라(AI-REQ-05) 설정 오류가 API 응답을 500 으로 만들면 안 된다. 호출한 쪽은 None 이면
    LLM 없이(규칙 기반으로) 동작한다. 로그에는 잘못된 설정 이름만 남기고 값은 남기지 않는다(키가 섞일 수 있다).
    """
    try:
        return AISettings()
    except ValidationError as error:
        names = ",".join(sorted({str(item["loc"][0]) for item in error.errors() if item["loc"]}))
        logger.warning("ai_settings invalid component=%s fields=%s llm=disabled", component, names)
        return None


def default_ai_settings() -> AISettings:
    """검증 없이 기본값만 담은 설정. 설정이 잘못돼 LLM 을 끈 서비스의 입력 제한 등에 쓴다(키 없음)."""
    return AISettings.model_construct()
