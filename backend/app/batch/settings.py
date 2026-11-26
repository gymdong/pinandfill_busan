from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.secrets import blank_key_is_no_key

BACKEND_DIR = Path(__file__).resolve().parents[2]


class BatchSettings(BaseSettings):
    """배치 수집 설정(FR-016). 환경변수 또는 backend/.env 에서 읽는다. 키·웹훅 URL 은 로그·오류에 내지 않는다."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", extra="ignore", hide_input_in_errors=True, env_ignore_empty=True
    )

    tourapi_service_key: SecretStr | None = None
    # 설정하면 수집 실패·복구 알림을 JSON 으로 POST 한다. 비우면 구조화 로그만 남긴다.
    admin_alert_webhook_url: SecretStr | None = None
    # 연속 실패 n 회면 마지막 실패 + min(이 값 × 2^(n-1) 분, 주기) 전에는 다시 시도하지 않는다.
    batch_backoff_base_min: int = Field(default=15, ge=1)

    _normalize_secrets = field_validator("tourapi_service_key", "admin_alert_webhook_url", mode="before")(
        blank_key_is_no_key
    )

    def tourapi_key(self) -> str | None:
        return self.tourapi_service_key.get_secret_value() if self.tourapi_service_key else None

    def webhook_url(self) -> str | None:
        return self.admin_alert_webhook_url.get_secret_value() if self.admin_alert_webhook_url else None
