from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlaceMatchSettings(BaseSettings):
    """카카오 장소와 공공 DB 장소의 매칭 기준. 환경변수 `PLACES_*` 로 바꿀 수 있다.

    core 의 ConfigService(app_config)가 생기면 그쪽으로 옮긴다.
    """

    model_config = SettingsConfigDict(env_prefix="PLACES_", extra="ignore")

    # FR-001: 좌표가 이 거리(m) 안에 있어야 같은 장소로 본다.
    match_radius_m: float = Field(100.0, gt=0)
    # 이름 유사도(0~1) 기준. 잠정값이며 대표 장소 100곳 측정 후 조정한다.
    name_similarity_threshold: float = Field(0.8, gt=0, le=1)
    # 검색어 최대 길이(글자). 잠정값
    search_query_max_length: int = Field(50, ge=1)
