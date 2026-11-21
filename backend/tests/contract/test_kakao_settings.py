"""KakaoSettings 설정 검사. 카카오를 부르지 않는다."""

import pytest
from pydantic import ValidationError

from app.adapters.kakao import KakaoSettings

TEST_KEY = "test-rest-key"


@pytest.mark.parametrize(
    "rect",
    [
        "129.32,34.86,128.74,35.40",  # 좌측 경도가 우측보다 크다
        "128.74,35.40,129.32,34.86",  # 하단 위도가 상단보다 크다
        "128.74,34.86,129.32",  # 숫자 3개
        "128.74,34.86,129.32,35.40,1",  # 숫자 5개
        "부산,34.86,129.32,35.40",
        "nan,34.86,129.32,35.40",
        "128.74,34.86,190,35.40",  # 경도 범위 밖
    ],
)
def test_bad_search_rect_fails_when_settings_load(rect):
    with pytest.raises(ValidationError) as error:
        KakaoSettings(rest_api_key=TEST_KEY, search_rect=rect, _env_file=None)
    # 설정 값과 키를 오류 문구에 싣지 않는다.
    assert rect not in str(error.value) and TEST_KEY not in str(error.value)


def test_default_search_rect_is_valid():
    assert KakaoSettings(rest_api_key=TEST_KEY, _env_file=None).search_rect == "128.74,34.86,129.32,35.40"
