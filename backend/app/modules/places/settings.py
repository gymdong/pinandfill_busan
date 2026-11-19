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
    # API-004 지도 길게 누르기: 이 반경(m) 안에서 아래 분류의 장소를 찾는다. 잠정값이다.
    # 카카오에는 '좌표의 모든 장소' 조회가 없어 분류마다 한 번씩 부른다(길게 누를 때마다 분류 수만큼 호출).
    nearby_radius_m: int = Field(100, ge=1, le=20000)
    # 관광명소·문화시설·음식점·카페. 여행 일정에 담을 만한 분류만 둔다. 잠정값이다.
    nearby_category_codes: tuple[str, ...] = ("AT4", "CT1", "FD6", "CE7")
    # 화면에 보여 줄 가까운 후보 수. 잠정값이다.
    nearby_max_results: int = Field(5, ge=1, le=15)
