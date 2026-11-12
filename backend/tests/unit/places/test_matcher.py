"""PlaceMatcher 단위 테스트. 장소 값은 모두 직접 만든 예시다."""

import pytest

from app.adapters.kakao import KakaoPlace
from app.modules.places import InMemoryPublicPlaceRepository, PlaceMatcher, PlaceMatchSettings, PublicPlace
from app.modules.places.geo import distance_m
from app.modules.places.matcher import name_similarity, normalize_name

BASE_LAT, BASE_LNG = 35.1500, 129.1200
# 위도 0.001도는 약 111m 다.
LAT_PER_M = 0.001 / 111.2


def public(place_id: str, name: str, north_m: float = 0.0) -> PublicPlace:
    return PublicPlace(id=place_id, name=name, lat=BASE_LAT + north_m * LAT_PER_M, lng=BASE_LNG, category="관광지")


def kakao(name: str, kakao_place_id: str = "900000001", north_m: float = 0.0) -> KakaoPlace:
    return KakaoPlace(
        kakao_place_id=kakao_place_id,
        name=name,
        lat=BASE_LAT + north_m * LAT_PER_M,
        lng=BASE_LNG,
        place_url=f"https://place.map.kakao.com/{kakao_place_id}",
    )


# 셸이나 CI 의 PLACES_* 환경변수에 영향받지 않도록 기준을 명시한다.
DEFAULTS = {"match_radius_m": 100.0, "name_similarity_threshold": 0.8}


def matcher(places: list[PublicPlace], overrides: dict[str, str] | None = None, **settings: float) -> PlaceMatcher:
    return PlaceMatcher(
        InMemoryPublicPlaceRepository(places, overrides), PlaceMatchSettings(**{**DEFAULTS, **settings})
    )


def test_distance_is_roughly_metric():
    assert distance_m(BASE_LAT, BASE_LNG, BASE_LAT + 100 * LAT_PER_M, BASE_LNG) == pytest.approx(100, abs=1)
    assert distance_m(BASE_LAT, BASE_LNG, BASE_LAT, BASE_LNG) == 0


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("용두산 공원", "용두산공원"),
        ("예시해변공원", "예시해변 공원 "),
        ("Ｆ１９６３", "f1963"),
        ("예시(본점)", "예시 본점"),
    ],
)
def test_spacing_symbols_and_width_do_not_matter(left, right):
    assert normalize_name(left) == normalize_name(right)
    assert name_similarity(left, right) == 1.0


def test_similarity_of_empty_name_is_zero():
    assert name_similarity("", "예시") == 0.0
    assert name_similarity("!!", "??") == 0.0


def test_matches_same_name_within_radius():
    place = public("p1", "예시해변공원", north_m=40)

    assert matcher([place]).match(kakao("예시 해변공원")) == place


def test_no_match_outside_radius():
    assert matcher([public("p1", "예시해변공원", north_m=130)]).match(kakao("예시해변공원")) is None


def test_no_match_when_name_differs():
    assert matcher([public("p1", "예시회센터", north_m=10)]).match(kakao("예시해변공원")) is None


def test_picks_most_similar_then_nearest():
    exact_far = public("far", "예시해변공원", north_m=80)
    exact_near = public("near", "예시해변공원", north_m=20)
    similar = public("similar", "예시해변광원", north_m=5)

    assert matcher([similar, exact_far, exact_near]).match(kakao("예시해변공원")) == exact_near
    assert matcher([similar]).match(kakao("예시해변공원")) == similar


def test_tie_is_broken_by_id_regardless_of_lookup_order():
    first, second = public("a", "예시해변공원", north_m=10), public("b", "예시해변공원", north_m=10)

    assert matcher([first, second]).match(kakao("예시해변공원")) == second
    assert matcher([second, first]).match(kakao("예시해변공원")) == second


@pytest.mark.parametrize(
    ("public_name", "kakao_name"),
    [
        ("예시해수욕장", "예시해수욕장 주차장"),
        ("예시시민공원", "예시시민공원 화장실"),
        ("국립예시박물관", "국립예시박물관 카페"),
        ("국립예시박물관", "카페 국립예시박물관"),
        ("예시해수욕장 주차장", "예시해수욕장"),
    ],
)
def test_facility_inside_a_place_is_not_auto_matched(public_name, kakao_name):
    """글자 유사도는 기준(0.8)을 넘지만 다른 장소일 수 있다. 본 장소의 영업시간을 붙이면 안 된다."""
    place = public("p1", public_name, north_m=10)
    assert name_similarity(public_name, kakao_name) >= 0.8

    assert matcher([place]).match(kakao(kakao_name)) is None
    assert matcher([place], {"900000001": "p1"}).match(kakao(kakao_name)) == place


def test_manual_override_wins_over_name_and_distance():
    override_target = public("manual", "예시유원지", north_m=900)
    lookalike = public("auto", "예시해변공원", north_m=5)

    result = matcher([override_target, lookalike], {"900000001": "manual"}).match(kakao("예시해변공원"))

    assert result == override_target


def test_override_to_missing_place_falls_back_to_rules():
    lookalike = public("auto", "예시해변공원", north_m=5)

    assert matcher([lookalike], {"900000001": "deleted"}).match(kakao("예시해변공원")) == lookalike


def test_shortened_name_needs_manual_override():
    """'예시대' 와 '예시대유원지' 처럼 줄여 부르는 이름은 유사도 기준에 못 미친다. 수동 매칭표로 잇는다."""
    place = public("p1", "예시대유원지", north_m=10)

    assert matcher([place]).match(kakao("예시대")) is None
    assert matcher([place], {"900000001": "p1"}).match(kakao("예시대")) == place


def test_thresholds_come_from_settings():
    place = public("p1", "예시해변광장", north_m=150)

    assert matcher([place]).match(kakao("예시해변공원")) is None
    assert matcher([place], match_radius_m=200, name_similarity_threshold=0.6).match(kakao("예시해변공원")) == place


def test_threshold_must_be_positive():
    with pytest.raises(ValueError):
        PlaceMatchSettings(name_similarity_threshold=0)


def test_rechecks_radius_even_if_repository_returns_far_places():
    class WideRepository(InMemoryPublicPlaceRepository):
        def find_near(self, lat, lng, radius_m):
            return super().find_near(lat, lng, radius_m * 10)

    repository = WideRepository([public("p1", "예시해변공원", north_m=300)])

    assert PlaceMatcher(repository, PlaceMatchSettings(**DEFAULTS)).match(kakao("예시해변공원")) is None


def test_settings_read_env(monkeypatch):
    monkeypatch.setenv("PLACES_MATCH_RADIUS_M", "50")

    assert PlaceMatchSettings().match_radius_m == 50
    assert PlaceMatchSettings().name_similarity_threshold == 0.8
