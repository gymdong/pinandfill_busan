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
    # 화면 타임아웃(45초)보다 짧게: 20초 × (재시도 1회 + 1) = 최대 40초.
    timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    # 후보로 보여 줄 최소 확신도, '찾았다'고 말할 최소 확신도(잠정, 표본으로 조정).
    min_candidate_confidence: float = Field(default=0.3, ge=0, le=1)
    min_found_confidence: float = Field(default=0.6, ge=0, le=1)
    # 업로드 상한(바이트). 화면이 보내기 전에 줄이므로 보통 훨씬 작다.
    # 공급자 이미지 한도(5MB)가 base64 기준이어도 넘지 않게 3.75MB 로 둔다.
    max_bytes: int = Field(default=3_750_000, gt=0)
    # 한 클라이언트(IP)가 1분에 보낼 수 있는 사진 수. 유료 호출 남용을 막는다(메모리 기준, 워커마다 따로).
    per_minute: int = Field(default=6, ge=1)

    def key(self) -> str | None:
        value = self.api_key.get_secret_value().strip() if self.api_key is not None else ""
        return value or None
