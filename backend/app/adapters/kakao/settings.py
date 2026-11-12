from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[3]


class KakaoSettings(BaseSettings):
    """카카오 로컬 API 설정. 환경변수 `KAKAO_*` 또는 backend/.env 에서 읽는다.

    core 의 ConfigService(app_config)가 생기면 키를 제외한 값은 그쪽으로 옮긴다.
    """

    model_config = SettingsConfigDict(env_prefix="KAKAO_", env_file=BACKEND_DIR / ".env", extra="ignore")

    rest_api_key: SecretStr
    base_url: str = "https://dapi.kakao.com"
    timeout_seconds: float = Field(3.0, gt=0)
    # 한 번의 검색으로 받을 결과 수. 카카오 상한은 15
    page_size: int = Field(15, ge=1, le=15)
    # 검색을 부산 주변으로 제한하는 사각 범위(좌측 X, 좌측 Y, 우측 X, 우측 Y). 잠정값이다.
    # 범위에 걸치는 김해·양산 등은 region_prefix 로 걸러 낸다.
    search_rect: str = "128.74,34.86,129.32,35.40"
    # 지번 주소가 이 값으로 시작하는 장소만 남긴다.
    region_prefix: str = "부산"
