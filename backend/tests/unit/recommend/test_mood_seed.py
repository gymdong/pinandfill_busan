"""저장소에 담긴 잠정 테마 태그 사전(data/seed/theme_tags)과 표본 장소 태그(data/samples/place_tags.csv) 점검."""

import pytest

from app.modules.places.samples import load_sample_places
from app.modules.recommend.mood import interpret_by_rules
from app.modules.recommend.mood_data import (
    PLACE_TAGS_FILE,
    THEME_TAGS_FILE,
    load_mood_data,
    load_place_tags,
    load_theme_tags,
)


def test_dictionary_has_10_to_15_unique_tags():
    tags = load_theme_tags()
    assert THEME_TAGS_FILE.is_file()
    assert 10 <= len(tags) <= 15  # 계획서 7장 1단계: 태그 10~15개
    assert len({tag.code for tag in tags}) == len(tags)


def test_every_place_tag_is_in_dictionary_and_every_tagged_place_exists():
    known = {tag.code for tag in load_theme_tags()}
    places = load_sample_places()
    by_place = load_place_tags()
    assert PLACE_TAGS_FILE.is_file()
    for place_id, codes in by_place.items():
        assert codes <= known, place_id
        assert places.place(place_id) is not None, place_id
    # 표본 장소 10곳이 모두 후보가 된다.
    assert len(load_mood_data(places).candidates()) == len(by_place) == 10


@pytest.mark.parametrize(
    ("text", "codes"),
    [
        ("바다", {"SEA_VIEW"}),
        ("조용한 바다 감성", {"SEA_VIEW"}),
        ("야경 보러 가고 싶어", {"NIGHT_VIEW"}),
        ("사람 적은 골목 산책", {"ALLEY_WALK"}),
        ("비 오는 날 갈 만한 미술관", {"INDOOR", "ART_CULTURE"}),
        ("바다 말고 숲", {"NATURE"}),
        ("자연 속에서 쉬고 싶어", {"NATURE", "HEALING"}),
        ("고즈넉한 사찰", {"TEMPLE"}),
    ],
)
def test_common_sentences_find_tags(text: str, codes: set[str]):
    tags, _ = interpret_by_rules(text, load_theme_tags())
    assert {tag.code for tag in tags} == codes


@pytest.mark.parametrize(
    ("text", "unrelated"),
    [
        ("절벽 위 카페", "TEMPLE"),
        ("아이스크림 먹으러", "FAMILY"),
        ("친절한 식당", "TEMPLE"),
        # 부분 일치로 다른 낱말에 섞이던 '공원'·'뷰'·'전통'은 사전에서 뺐다.
        ("놀이공원 가고 싶어", "NATURE"),
        ("리뷰 좋은 곳", "VIEWPOINT"),
        ("인터뷰 영상에 나온 곳", "VIEWPOINT"),
        ("전통시장 구경", "TEMPLE"),
        # '절에'·'자연'도 '계절에'·'자연스러운'에 섞여 뺐다.
        ("이 계절에 가기 좋은 곳", "TEMPLE"),
        ("가을 계절에 걷기", "TEMPLE"),
        ("자연스러운 분위기 카페", "NATURE"),
    ],
)
def test_short_words_do_not_trigger_unrelated_tags(text: str, unrelated: str):
    tags, _ = interpret_by_rules(text, load_theme_tags())
    assert unrelated not in {tag.code for tag in tags}


def test_amusement_park_is_activity_only():
    tags, _ = interpret_by_rules("놀이공원 가고 싶어", load_theme_tags())
    assert {tag.code for tag in tags} == {"ACTIVITY"}
