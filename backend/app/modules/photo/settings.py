"""사진으로 장소 찾기(FR-012) 설정. 환경변수 `PHOTO_*`·`ANTHROPIC_API_KEY` 또는 backend/.env 에서 읽는다."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[3]


class PhotoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHOTO_", env_file=BACKEND_DIR / ".env", extra="ignore")

    # 비어 있으면 사진 찾기를 끈다(503). 값은 로그·오류에 남기지 않는다.
    api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "PHOTO_API_KEY"))
    model: str = "claude-opus-5-5"
    # 분류 한 번이라 낮은 effort 로 충분하다. 품질이 모자라면 medium 으로 올린다.
    effort: Literal["low", "medium", "high"] = "low"
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    # 후보로 보여 줄 최소 확신도, '찾았다'고 말할 최소 확신도(잠정, 표본으로 조정).
    min_candidate_confidence: float = Field(default=0.3, ge=0, le=1)
    min_found_confidence: float = Field(default=0.6, ge=0, le=1)
    # 업로드 상한(바이트). 화면이 보내기 전에 줄이므로 보통 훨씬 작다.
    max_bytes: int = Field(default=5 * 1024 * 1024, gt=0)

    def key(self) -> str | None:
        value = self.api_key.get_secret_value().strip() if self.api_key is not None else ""
        return value or None
