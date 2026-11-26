"""카카오 장소 ID 는 요청 단계에서 DB 열 길이(blocks.kakao_place_id) 안으로 막는다 (#42 리뷰)."""

import pytest
from pydantic import ValidationError

from app.db.models import BlockRow
from app.modules.engine.schemas import KakaoPlaceRef
from app.modules.trips.schemas import KakaoPlaceKey

COLUMN_LENGTH = BlockRow.__table__.c.kakao_place_id.type.length
URL = "https://place.map.kakao.com/{}"


@pytest.mark.parametrize("model", [KakaoPlaceKey, KakaoPlaceRef])
def test_id_longer_than_the_column_is_rejected_before_the_database(model):
    too_long = "1" * (COLUMN_LENGTH + 1)
    with pytest.raises(ValidationError):
        model.model_validate({"kakaoPlaceId": too_long, "placeUrl": URL.format(too_long)})


@pytest.mark.parametrize("model", [KakaoPlaceKey, KakaoPlaceRef])
def test_id_at_the_column_length_is_accepted(model):
    longest = "1" * COLUMN_LENGTH
    model.model_validate({"kakaoPlaceId": longest, "placeUrl": URL.format(longest)})
