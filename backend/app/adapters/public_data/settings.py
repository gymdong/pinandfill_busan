from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.secrets import blank_key_is_no_key

BACKEND_DIR = Path(__file__).resolve().parents[3]
REGION_CODES = BACKEND_DIR.parent / "data" / "seed" / "crowd" / "busan_region_codes.csv"


class VisitorDataSettings(BaseSettings):
    """DATA-06·07 수집 설정(FR-008·016). 환경변수 또는 backend/.env 에서 읽는다. 키는 로그·오류에 내지 않는다.

    키는 공공데이터포털 일반 인증키(Decoding)다. 비우면 키가 없는 것으로 보고 잡은 호출 없이 FAILED 로 끝난다.
    """

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", extra="ignore", hide_input_in_errors=True, env_ignore_empty=True
    )

    data06_service_key: SecretStr | None = None
    data07_service_key: SecretStr | None = None
    public_data_timeout_s: float = Field(default=10.0, gt=0)
    # 한 번 요청에 받는 최대 행 수. 응답 totalCount 가 이보다 크면 잘린 자료로 계산하지 않고 실패한다.
    public_data_page_size: int = Field(default=1000, ge=1)
    # DATA-06: 하루 1회 호출로 최근 N 일(기준 기간)을 받아 같은 평일/주말 평균으로 나눈다.
    data06_baseline_days: int = Field(default=28, ge=1)
    # DATA-06: 오늘(KST)에서 이만큼 앞선 날을 기준 기간 마지막 날로 둔다(자료 공개 지연, 명세 확인 필요).
    data06_lag_days: int = Field(default=3, ge=1)
    crowd_region_codes_path: Path = REGION_CODES

    _normalize_secrets = field_validator("data06_service_key", "data07_service_key", mode="before")(blank_key_is_no_key)

    def data06_key(self) -> str | None:
        return self.data06_service_key.get_secret_value() if self.data06_service_key else None

    def data07_key(self) -> str | None:
        return self.data07_service_key.get_secret_value() if self.data07_service_key else None
