"""API-005 장소 상세(표본 공급자) 단위 테스트. 장소 값은 직접 만든 예시다."""

from datetime import date
from pathlib import Path

import pytest

from app.modules.places.detail import PlaceDetailService, PlaceNotFoundError, SamplePlaceDetails
from app.modules.places.samples import load_sample_places

PLACES = (
    "﻿name,lat,lng,category,indoor_outdoor,tourapi_contentid,default_stay_min,"
    "closed_days_raw,source_label_original,checked_at\n"
    '예시 미술관,35.10,129.10,문화시설,실내,100,90,매주 월요일,"한국관광공사 TourAPI, 예시 홈페이지",2026-11-01\n'
    "예시 공원,35.20,129.20,관광지,실외,200,,,,2026-11-02\n"
    "예시 정원,35.30,129.30,관광지,뜰,300,30,,예시 기관,\n"
)
HOURS = (
    "﻿tourapi_contentid,day_type,open_time,close_time,break_start,break_end,is_closed\n"
    "100,TUE,10:00,18:00,12:00,13:00,FALSE\n"
    "100,MON,,,,,TRUE\n"
)
MAPPING = (
    "﻿tourapi_contentid,kakao_place_id,kakao_place_url,match_status\n"
    "100,900000001,https://place.map.kakao.com/900000001,MATCHED\n"
)


def details(tmp_path: Path) -> SamplePlaceDetails:
    (tmp_path / "places_sample.csv").write_text(PLACES, encoding="utf-8")
    (tmp_path / "place_hours.csv").write_text(HOURS, encoding="utf-8")
    (tmp_path / "kakao_id_mapping.csv").write_text(MAPPING, encoding="utf-8")
    return SamplePlaceDetails(load_sample_places(tmp_path))


def test_detail_has_place_hours_and_source(tmp_path):
    detail = details(tmp_path).place_detail("100")
    assert detail is not None
    place = detail.place
    assert (place.id, place.name, place.category, place.source) == ("100", "예시 미술관", "문화시설", "PUBLIC")
    assert (place.closed_days_text, place.default_stay_min, place.indoor_outdoor) == ("매주 월요일", 90, "실내")
    assert place.ref_date == date(2026, 11, 1)
    # 요일 순서대로, 휴게시간과 휴무를 그대로 싣는다.
    assert [(h.day_type, h.is_closed) for h in detail.hours] == [("MON", True), ("TUE", False)]
    assert detail.hours[1].model_dump(mode="json", by_alias=True) == {
        "dayType": "TUE",
        "openTime": "10:00",
        "closeTime": "18:00",
        "breakStart": "12:00",
        "breakEnd": "13:00",
        "isClosed": False,
    }
    assert [(s.org, s.ref_date) for s in detail.sources] == [("한국관광공사 TourAPI, 예시 홈페이지", date(2026, 11, 1))]


def test_missing_values_are_not_invented(tmp_path):
    park = details(tmp_path).place_detail("200")
    assert park is not None
    # 표본 '실외'는 SDD 값 '야외'로 맞춘다.
    assert park.place.indoor_outdoor == "야외"
    # 체류시간·휴무·설명·출처·영업시간·사진·혼잡이 없으면 비워 둔다(NFR-012, FR-014).
    assert (park.place.default_stay_min, park.place.closed_days_text, park.place.description) == (None, None, None)
    assert (park.hours, park.sources, park.photos, park.crowd, park.weather) == ((), (), (), None, None)


def test_unknown_indoor_value_is_dropped_and_source_keeps_org_without_date(tmp_path):
    garden = details(tmp_path).place_detail("300")
    assert garden is not None
    assert garden.place.indoor_outdoor is None
    # 기준일이 없어도 기관명은 남기고, 날짜는 만들지 않는다.
    assert garden.place.ref_date is None
    assert [(s.org, s.ref_date) for s in garden.sources] == [("예시 기관", None)]


@pytest.mark.parametrize("place_id", ["999", "900000001"])
def test_unknown_and_kakao_ids_are_not_found(tmp_path, place_id):
    # 카카오 장소 ID 는 매칭표에 있어도 공공 장소 상세가 아니다.
    with pytest.raises(PlaceNotFoundError):
        PlaceDetailService(details(tmp_path)).get(place_id)
