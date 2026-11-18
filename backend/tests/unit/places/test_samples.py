"""표본 CSV 장소 공급자 단위 테스트. 장소 값은 직접 만든 예시다(실제 표본 파일은 마지막 시험에서만 읽는다)."""

from datetime import date, time
from pathlib import Path

from app.modules.engine.interfaces import PlaceDataProvider
from app.modules.engine.schemas import KakaoPlaceRef, PublicPlaceRef
from app.modules.places import HoursStatus, hours_status
from app.modules.places.samples import SAMPLE_DIR, load_sample_places
from app.modules.trips.schemas import KakaoPlaceKey, PublicPlaceInput

PLACES = """﻿name,lat,lng,category,tourapi_contentid,default_stay_min,checked_at
예시 미술관,35.10,129.10,문화시설,100,90,2026-11-01
예시 공원,35.20,129.20,관광지,200,,2026-11-02
"예시
좌표 없음",,,관광지,300,30,2026-11-02
"""
HOURS = """﻿tourapi_contentid,day_type,open_time,close_time,break_start,break_end,is_closed
100,MON,,,,,TRUE
100,TUE,10:00,18:00,,,FALSE
"""
MAPPING = """﻿tourapi_contentid,kakao_place_id,kakao_place_url,match_status
100,900000001,https://place.map.kakao.com/900000001,MATCHED
200,900000002,https://place.map.kakao.com/900000002,PENDING
"""
MONDAY, TUESDAY, WEDNESDAY = date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18)


def samples(tmp_path: Path):
    (tmp_path / "places_sample.csv").write_text(PLACES, encoding="utf-8")
    (tmp_path / "place_hours.csv").write_text(HOURS, encoding="utf-8")
    (tmp_path / "kakao_id_mapping.csv").write_text(MAPPING, encoding="utf-8")
    return load_sample_places(tmp_path)


def test_is_an_engine_place_provider(tmp_path):
    assert isinstance(samples(tmp_path), PlaceDataProvider)


def test_known_hours_for_the_trip_weekday(tmp_path):
    details = samples(tmp_path).get(PublicPlaceRef(place_id="100"), on_date=TUESDAY)
    assert (details.name, details.lat, details.lng, details.category) == ("예시 미술관", 35.10, 129.10, "문화시설")
    assert details.ref_date == date(2026, 11, 1)
    assert details.hours is not None
    assert (details.hours.open_time, details.hours.close_time, details.hours.is_closed) == (time(10), time(18), False)
    assert samples(tmp_path).get(PublicPlaceRef(place_id="100"), on_date=MONDAY).hours.is_closed


def test_missing_hours_stay_unknown(tmp_path):
    data = samples(tmp_path)
    # 행이 없는 요일과 시간표가 없는 장소는 지어내지 않고 None('확인 필요')이다.
    assert data.get(PublicPlaceRef(place_id="100"), on_date=WEDNESDAY).hours is None
    assert data.get(PublicPlaceRef(place_id="200"), on_date=TUESDAY).hours is None


def test_unknown_place_has_no_display_data(tmp_path):
    ref = PublicPlaceRef(place_id="999")
    details = samples(tmp_path).get(ref, on_date=TUESDAY)
    assert details.place_ref == ref
    assert (details.name, details.lat, details.lng, details.hours) == (None, None, None, None)


def test_rows_without_coordinates_are_skipped(tmp_path):
    data = samples(tmp_path)
    assert data.get(PublicPlaceRef(place_id="300"), on_date=TUESDAY).name is None
    assert data.stay_min(PublicPlaceInput(place_id="300")) is None


def test_stay_minutes_come_only_from_the_sample(tmp_path):
    data = samples(tmp_path)
    assert data.stay_min(PublicPlaceInput(place_id="100")) == 90
    assert data.stay_min(PublicPlaceInput(place_id="200")) is None
    assert data.stay_min(PublicPlaceInput(place_id="999")) is None
    # 카카오 장소는 확정된 매칭표로 이어진 공공 장소 값만 쓴다.
    matched = KakaoPlaceKey(kakao_place_id="900000001", place_url="https://place.map.kakao.com/900000001")
    pending = KakaoPlaceKey(kakao_place_id="900000002", place_url="https://place.map.kakao.com/900000002")
    assert data.stay_min(matched) == 90
    assert data.stay_min(pending) is None


def test_kakao_ref_is_never_resolved(tmp_path):
    ref = KakaoPlaceRef(kakao_place_id="900000001", placeUrl="https://place.map.kakao.com/900000001")
    details = samples(tmp_path).get(ref, on_date=TUESDAY)
    assert (details.name, details.lat, details.hours) == (None, None, None)


def test_repository_uses_the_same_places_and_mapping(tmp_path):
    repository = samples(tmp_path).repository()
    matched = repository.find_by_kakao_id("900000001")
    assert matched is not None and matched.id == "100"
    assert hours_status(matched) == HoursStatus.KNOWN
    assert repository.find_by_kakao_id("900000002") is None
    assert [place.id for place in repository.find_near(35.20, 129.20, 10)] == ["200"]


def test_missing_directory_gives_empty_data(tmp_path):
    data = load_sample_places(tmp_path / "missing")
    assert data.get(PublicPlaceRef(place_id="100"), on_date=TUESDAY).name is None


def test_repository_sample_files_load():
    data = load_sample_places(SAMPLE_DIR)
    details = data.get(PublicPlaceRef(place_id="126848"), on_date=TUESDAY)
    assert details.name and details.lat is not None and details.hours is not None
