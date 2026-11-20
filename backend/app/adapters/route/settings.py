from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[3]


class TMAPSettings(BaseSettings):
    """TMAP 경로 API 설정. 환경변수 `TMAP_*` 또는 backend/.env 에서 읽는다.

    키가 없으면 경로를 조회하지 않는다. core 의 ConfigService(app_config)가 생기면 키를 제외한 값은 그쪽으로 옮긴다.
    """

    model_config = SettingsConfigDict(env_prefix="TMAP_", env_file=BACKEND_DIR / ".env", extra="ignore")

    api_key: SecretStr | None = None
    timeout_seconds: float = Field(default=5.0, gt=0)
    # 프로세스 안 하루 호출 상한. 잠정값이며 발급받은 요금제 한도에 맞춘다.
    daily_call_limit: int = Field(default=1000, ge=0)


class ODsaySettings(BaseSettings):
    """ODsay 대중교통 경로 API 설정(TMAP 실패 시 예비). 환경변수 `ODSAY_*` 또는 backend/.env 에서 읽는다."""

    model_config = SettingsConfigDict(env_prefix="ODSAY_", env_file=BACKEND_DIR / ".env", extra="ignore")

    api_key: SecretStr | None = None
    timeout_seconds: float = Field(default=5.0, gt=0)
    # 잠정값이며 발급받은 요금제 한도에 맞춘다.
    daily_call_limit: int = Field(default=1000, ge=0)
