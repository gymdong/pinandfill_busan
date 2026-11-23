from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.secrets import blank_key_is_no_key

BACKEND_DIR = Path(__file__).resolve().parents[3]


class KakaoSettings(BaseSettings):
    """카카오 로컬 API 설정. 환경변수 `KAKAO_*` 또는 backend/.env 에서 읽는다.

    core 의 ConfigService(app_config)가 생기면 키를 제외한 값은 그쪽으로 옮긴다.
    """

    model_config = SettingsConfigDict(
        env_prefix="KAKAO_", env_file=BACKEND_DIR / ".env", extra="ignore", hide_input_in_errors=True
    )

    # 빈 값·공백뿐인 키는 None 이 되어 검증 오류(rest_api_key)로 끝난다. 앱은 그때 장소 검색을 끈다.
    rest_api_key: SecretStr
    _normalize_key = field_validator("rest_api_key", mode="before")(blank_key_is_no_key)
    base_url: str = "https://dapi.kakao.com"
    timeout_seconds: float = Field(3.0, gt=0)
    # 한 번의 검색으로 받을 결과 수. 카카오 상한은 15
    page_size: int = Field(15, ge=1, le=15)
    # 검색을 부산 주변으로 제한하는 사각 범위(좌측 X, 좌측 Y, 우측 X, 우측 Y). 잠정값이다.
    # 범위에 걸치는 김해·양산 등은 region_prefix 로 걸러 낸다.
    search_rect: str = "128.74,34.86,129.32,35.40"
    # 지번 주소가 이 값으로 시작하는 장소만 남긴다.
    region_prefix: str = "부산"

    @field_validator("search_rect")
    @classmethod
    def valid_rect(cls, value: str) -> str:
        """경도·위도 숫자 4개이고 좌측<우측, 하단<상단이어야 한다. 잘못되면 앱이 시작할 때 실패한다.

        요청마다 범위를 읽다가 실패하면 장소 검색이 원인 모를 500 으로 끝나므로 설정 단계에서 막는다.
        """
        try:
            min_lng, min_lat, max_lng, max_lat = (float(part) for part in value.split(","))
        except ValueError:
            raise ValueError("search_rect must be four numbers: min_lng,min_lat,max_lng,max_lat") from None
        # NaN 은 어떤 비교도 거짓이라 여기서 함께 걸러진다.
        if not (-180 <= min_lng < max_lng <= 180 and -90 <= min_lat < max_lat <= 90):
            raise ValueError("search_rect must have min < max within longitude/latitude ranges")
        return value
