"""기상청 예보(FR-013) 설정. `KMA_SERVICE_KEY` 가 없으면 같은 공공데이터포털 계정의 `DATA04_SERVICE_KEY` 를 쓴다."""

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[3]


class WeatherSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore", env_ignore_empty=True)

    kma_service_key: SecretStr | None = None
    data04_service_key: SecretStr | None = None
    kma_timeout_s: float = Field(default=10.0, gt=0, le=60)
    # 같은 격자·발표의 예보를 다시 받지 않는 시간(초). 단기예보는 3시간마다 발표된다.
    kma_cache_s: int = Field(default=1800, ge=0)
    # 비 예보로 보는 강수확률(%). 강수형태(PTY)가 비·눈이면 확률과 관계없이 비 예보다.
    rain_pop: int = Field(default=60, ge=0, le=100)
    # 해안 장소 강풍 경고 기준 풍속(m/s, 잠정). 기상청 강풍주의보(육상 14m/s)보다 낮게 둔다.
    coast_wind_ms: float = Field(default=9.0, ge=0)

    def key(self) -> str | None:
        for secret in (self.kma_service_key, self.data04_service_key):
            value = secret.get_secret_value().strip() if secret is not None else ""
            if value:
                return value
        return None
