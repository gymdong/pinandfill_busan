from pydantic import BaseModel, ConfigDict, Field


class KakaoPlace(BaseModel):
    """카카오 장소 검색 결과 1건.

    요청을 처리하는 동안에만 쓴다. 카카오 공식 답변(D6)에 따라 DB·캐시·로그에 남길 수 있는 값은
    `kakao_place_id` 와 `place_url` 뿐이다. 카카오는 영업시간을 주지 않는다.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    # 숫자로만 된 ID 만 받는다. 표준 장소 URL(https://place.map.kakao.com/{id})을 만드는 데 쓰인다.
    kakao_place_id: str = Field(validation_alias="id", pattern=r"^[0-9]+$")
    name: str = Field(validation_alias="place_name")
    # 카카오는 좌표를 문자열로 준다. x 가 경도, y 가 위도다. NaN·무한대와 범위 밖 값은 받지 않는다.
    lng: float = Field(validation_alias="x", ge=-180, le=180, allow_inf_nan=False)
    lat: float = Field(validation_alias="y", ge=-90, le=90, allow_inf_nan=False)
    category_name: str = ""
    category_group_code: str = ""
    address: str = Field("", validation_alias="address_name")
    road_address: str = Field("", validation_alias="road_address_name")
    place_url: str
