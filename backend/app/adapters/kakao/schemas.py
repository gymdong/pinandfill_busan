from pydantic import BaseModel, ConfigDict, Field


class KakaoPlace(BaseModel):
    """카카오 장소 검색 결과 1건.

    요청을 처리하는 동안에만 쓴다. 카카오 공식 답변(D6)에 따라 DB·캐시·로그에 남길 수 있는 값은
    `kakao_place_id` 와 `place_url` 뿐이다. 카카오는 영업시간을 주지 않는다.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    kakao_place_id: str = Field(validation_alias="id")
    name: str = Field(validation_alias="place_name")
    # 카카오는 좌표를 문자열로 준다. x 가 경도, y 가 위도다.
    lng: float = Field(validation_alias="x")
    lat: float = Field(validation_alias="y")
    category_name: str = ""
    category_group_code: str = ""
    address: str = Field("", validation_alias="address_name")
    road_address: str = Field("", validation_alias="road_address_name")
    place_url: str
