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
    ],
)
def test_common_sentences_find_tags(text: str, codes: set[str]):
    tags, _ = interpret_by_rules(text, load_theme_tags())
    assert {tag.code for tag in tags} == codes


@pytest.mark.parametrize("text", ["절벽 위 카페", "아이스크림 먹으러", "친절한 식당"])
def test_short_words_do_not_trigger_unrelated_tags(text: str):
    tags, _ = interpret_by_rules(text, load_theme_tags())
    assert not {"TEMPLE", "FAMILY"} & {tag.code for tag in tags}
