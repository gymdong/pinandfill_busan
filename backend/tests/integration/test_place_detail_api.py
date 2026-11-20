"""API-005 장소 상세 통합 테스트. 외부 API 를 부르지 않는다(표본 CSV 만 읽음)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.modules.places.detail import PlaceDetailService, SamplePlaceDetails
from app.modules.places.samples import load_sample_places

PLACES = (
    "﻿name,lat,lng,category,indoor_outdoor,tourapi_contentid,default_stay_min,"
    "closed_days_raw,source_label_original,checked_at\n"
    "예시 미술관,35.10,129.10,문화시설,실내,100,90,매주 월요일,예시 기관,2026-11-01\n"
)
HOURS = "﻿tourapi_contentid,day_type,open_time,close_time,break_start,break_end,is_closed\n100,TUE,10:00,18:00,,,FALSE\n"


@pytest.fixture
def client(tmp_path: Path):
    (tmp_path / "places_sample.csv").write_text(PLACES, encoding="utf-8")
    (tmp_path / "place_hours.csv").write_text(HOURS, encoding="utf-8")
    service = PlaceDetailService(SamplePlaceDetails(load_sample_places(tmp_path)))
    with TestClient(create_app(Settings(app_name="Backend test"), place_detail_service=service)) as test_client:
        yield test_client


def test_returns_detail_in_frontend_shape(client):
    response = client.get("/api/places/100", params={"date": "2026-11-17"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"place", "hours", "photos", "weather", "crowd", "sources"}
    assert body["place"] == {
        "id": "100",
        "name": "예시 미술관",
        "lat": 35.10,
        "lng": 129.10,
        "category": "문화시설",
        "source": "PUBLIC",
        "description": None,
        "closedDaysText": "매주 월요일",
        "defaultStayMin": 90,
        "indoorOutdoor": "실내",
        "rating": None,
        "refDate": "2026-11-01",
    }
    assert body["hours"] == [
        {
            "dayType": "TUE",
            "openTime": "10:00",
            "closeTime": "18:00",
            "breakStart": None,
            "breakEnd": None,
            "isClosed": False,
        }
    ]
    assert (body["photos"], body["weather"], body["crowd"]) == ([], None, None)
    assert body["sources"] == [{"org": "예시 기관", "refDate": "2026-11-01"}]


def test_date_is_optional(client):
    assert client.get("/api/places/100").status_code == 200


@pytest.mark.parametrize("place_id", ["999", "900000001"])
def test_unknown_or_kakao_place_is_404(client, place_id):
    response = client.get(f"/api/places/{place_id}")
    assert response.status_code == 404
    assert response.json()["error"]["id"] == "ERR-016"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("bad", ["2026-13-01", "20261117", "내일"])
def test_bad_date_is_400(client, bad):
    response = client.get("/api/places/100", params={"date": bad})
    assert response.status_code == 400
    assert response.json()["error"]["id"] == "ERR-001"


def test_search_path_is_not_taken_as_place_id(client):
    # 카카오 키가 없어 검색 서비스가 없으면 검색 경로의 503 이 나와야 한다('search' 장소의 404 가 아니다).
    response = client.get("/api/places/search", params={"q": "예시"})
    assert (response.status_code, response.json()["error"]["id"]) == (503, "ERR-017")


def test_default_app_serves_sample_place_without_keys():
    # conftest 가 카카오 키를 비운다. 장소 상세는 외부 API 없이 표본으로 응답한다.
    with TestClient(create_app(Settings(app_name="Backend test"))) as client:
        response = client.get("/api/places/126848")
    assert response.status_code == 200
    body = response.json()
    assert body["place"]["id"] == "126848"
    assert body["hours"] and body["sources"]
