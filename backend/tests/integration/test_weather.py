"""FR-013 날씨(API-016)와 플랜 B 비 트리거. 기상청은 httpx MockTransport 가짜 응답이다(실제 호출 없음)."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi.testclient import TestClient

from app.main import _stay, create_app
from app.modules.engine.initial import InitialSchedulePlanner
from app.modules.engine.service import BasicItineraryEngine
from app.modules.places.samples import load_sample_places
from app.modules.plan_b.service import PlanBPlanner
from app.modules.recommend.waypoints import PublicPlaceCandidates
from app.modules.trips.initial import PublicStayDurations
from app.modules.trips.repository import FakeTripRepository
from app.modules.trips.service import TripService
from app.modules.weather.grid import to_grid
from app.modules.weather.kma import KmaClient, mid_base, short_base
from app.modules.weather.router import outdoor_of
from app.modules.weather.service import WeatherService
from app.modules.weather.settings import WeatherSettings

KST = ZoneInfo("Asia/Seoul")
TRIP = {"dates": {"start": "2026-12-02", "end": "2026-12-02"}, "dayStart": "09:00", "dayEnd": "20:00", "mode": "WALK"}
NOW = datetime(2026, 12, 1, 9, 30, tzinfo=KST)  # 08시 단기 발표, 06시 중기 발표
TOMORROW = date(2026, 12, 2)


def test_grid_and_issue_times() -> None:
    assert to_grid(35.1796, 129.0756) == (98, 76)  # 부산시청
    assert short_base(NOW) == datetime(2026, 12, 1, 8, tzinfo=KST)
    assert short_base(datetime(2026, 12, 1, 2, 5, tzinfo=KST)) == datetime(2026, 11, 30, 23, tzinfo=KST)
    assert mid_base(NOW) == datetime(2026, 12, 1, 6, tzinfo=KST)
    assert mid_base(datetime(2026, 12, 1, 5, tzinfo=KST)) == datetime(2026, 11, 30, 18, tzinfo=KST)


def _ok(items: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(200, json={"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": items}}}})


def _kma(rain_hours: set[int], calls: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path.rsplit("/", 1)[-1])
        assert request.url.params["serviceKey"] == "test-key"
        if request.url.path.endswith("getVilageFcst"):
            items = []
            for hour in range(24):
                values = {"POP": "70" if hour in rain_hours else "10", "PTY": "1" if hour in rain_hours else "0"}
                values |= {"SKY": "4", "TMP": "8", "WSD": "11" if hour == 15 else "3"}
                items += [
                    {
                        "category": k,
                        "fcstDate": TOMORROW.strftime("%Y%m%d"),
                        "fcstTime": f"{hour:02d}00",
                        "fcstValue": v,
                    }
                    for k, v in values.items()
                ]
            return httpx.Response(
                200, json={"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": items}}}}
            )
        if request.url.path.endswith("getMidLandFcst"):
            item = {"rnSt7Am": 20, "rnSt7Pm": 60, "wf7Am": "맑음", "wf7Pm": "흐리고 비"}
        else:
            item = {"taMin7": 4, "taMax7": 12}
        return httpx.Response(
            200, json={"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": [item]}}}}
        )

    return httpx.MockTransport(handler)


def _weather(rain_hours: set[int], calls: list[str]) -> WeatherService:
    client = KmaClient("test-key", transport=_kma(rain_hours, calls))
    return WeatherService(client, WeatherSettings(_env_file=None), clock=lambda: NOW.astimezone(UTC))


def test_short_mid_and_out_of_range_with_cache() -> None:
    calls: list[str] = []
    weather = _weather({14}, calls)
    short = weather.forecast(35.15, 129.11, TOMORROW, 14)
    assert short is not None and short.scope == "SHORT" and short.rain and short.pty == "비" and short.pop == 70
    assert weather.forecast(35.15, 129.11, TOMORROW, 10).rain is False  # type: ignore[union-attr]
    mid = weather.forecast(35.15, 129.11, date(2026, 12, 8), 15)  # 12/1 06시 발표 + 7일, 오후
    assert mid is not None and mid.scope == "MID" and mid.pop == 60 and mid.sky == "흐리고 비"
    assert (mid.temp_min, mid.temp_max, mid.rain) == (4, 12, False)  # 일 단위로는 자동 조정하지 않는다
    assert weather.forecast(35.15, 129.11, date(2026, 12, 20), 12) is None
    assert weather.rain(35.15, 129.11, date(2026, 12, 8), 15) is None
    # 같은 격자·발표는 다시 받지 않는다.
    assert calls.count("getVilageFcst") == 1 and calls.count("getMidLandFcst") == 1


def test_failure_is_no_forecast() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"response": {"header": {"resultCode": "30", "resultMsg": "SERVICE_KEY_IS_NOT_REGISTERED"}}}
        )

    weather = WeatherService(KmaClient("k", transport=httpx.MockTransport(broken)), WeatherSettings(_env_file=None))
    assert weather.forecast(35.15, 129.11, TOMORROW, 10) is None


def _app(weather: WeatherService) -> TestClient:
    places = load_sample_places()
    engine = BasicItineraryEngine(places, _Twenty())
    candidates = PublicPlaceCandidates(
        lambda: [item.place.id for item in places.all()],
        lambda pid: _stay(places, pid),
    )
    service = TripService(
        FakeTripRepository({}),
        engine,
        places.stay_min,
        initial_planner=InitialSchedulePlanner(engine, PublicStayDurations(places.stay_min)),
        plan_b=PlanBPlanner(
            engine, places, candidates, crowd=None, rain=weather, outdoor=lambda pid: outdoor_of(places, pid)
        ),
    )
    return TestClient(create_app(trip_service=service, weather_service=weather))


class _Twenty:
    def estimate(self, origin: object, destination: object, *, mode: str):  # type: ignore[no-untyped-def]
        from app.modules.engine.interfaces import RouteEstimate

        return RouteEstimate(20, "ESTIMATED", datetime(2026, 12, 1, tzinfo=UTC))


def _trip(client: TestClient) -> dict[str, dict[str, object]]:
    trip = {
        "dates": {"start": "2026-12-02", "end": "2026-12-02"},
        "dayStart": "09:00",
        "dayEnd": "20:00",
        "mode": "TRANSIT",
    }
    trip_id = client.post("/api/trips", json=trip).json()["tripId"]
    fixed = {"dayNo": 1, "start": "10:00", "end": "11:00"}
    selections = [
        {"clientId": "130166", "place": {"placeId": "130166"}, "dayNo": 1, "fixedWindow": fixed},
        {"clientId": "126078", "place": {"placeId": "126078"}, "stayMin": 60},  # 광안리(실외) 11:20
        {
            "clientId": "126658",
            "place": {"placeId": "126658"},
            "dayNo": 1,
            "fixedWindow": {**fixed, "start": "15:00", "end": "16:00"},
        },
    ]
    created = client.post(
        f"/api/trips/{trip_id}/schedule", json={"initial": {"policy": "FIRST_FEASIBLE", "selections": selections}}
    )
    assert created.status_code == 200, created.text
    blocks = {b["place"]["id"]: b for b in created.json()["days"][0]["blocks"]}
    return {"trip": {"id": trip_id}, **blocks}


def test_trip_weather_marks_outdoor_rain_and_coastal_wind() -> None:
    with _app(_weather({11}, [])) as client:
        blocks = _trip(client)
        trip_id = blocks["trip"]["id"]
        response = client.get(f"/api/trips/{trip_id}/weather")
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    rows = {row["blockId"]: row for row in response.json()["blocks"]}
    beach = rows[blocks["126078"]["id"]]
    assert beach["scope"] == "SHORT" and beach["forecast"]["rain"] and beach["outdoor"] is True
    assert "실외 장소인데 비 예보가 있어요" in beach["warnings"]
    museum = rows[blocks["130166"]["id"]]
    assert museum["outdoor"] is False and museum["warnings"] == []
    taejongdae = rows[blocks["126658"]["id"]]
    assert taejongdae["forecast"]["wind"] == 11 and not any(
        "바람" in w for w in taejongdae["warnings"]
    )  # 해안 단어 없음


def test_rain_on_outdoor_block_triggers_plan_b_with_dry_or_indoor_options() -> None:
    with _app(_weather({11}, [])) as client:
        blocks = _trip(client)
        trip_id = blocks["trip"]["id"]
        body = client.get(f"/api/trips/{trip_id}/plan-b", params={"blockId": blocks["126078"]["id"]}).json()
        reorder_id = next(o["id"] for o in body["options"] if o["kind"] == "REORDER")
        applied = client.post(f"/api/trips/{trip_id}/plan-b/apply", json={"optionId": reorder_id})
    assert body["trigger"] == "RAIN"
    keep, reorder, replace = body["options"]
    assert reorder["available"] and reorder["arriveAt"] == "16:20"  # 태종대 뒤로: 비 그침
    # 표본의 실내 장소는 이미 일정에 있는 미술관뿐이고, 같은 격자에 11시 비 → 대체 장소 없음.
    assert replace["available"] is False and "실내" in replace["note"]
    assert applied.status_code == 200, applied.text


def test_no_key_disables_weather() -> None:
    with TestClient(create_app()) as client:
        trip_id = client.post(
            "/api/trips",
            json={
                "dates": {"start": "2026-12-02", "end": "2026-12-02"},
                "dayStart": "09:00",
                "dayEnd": "20:00",
                "mode": "WALK",
            },
        ).json()["tripId"]
        response = client.get(f"/api/trips/{trip_id}/weather")
    assert response.status_code == 503 and response.json()["error"]["id"] == "ERR-012"


def test_empty_or_failed_results_are_retried_soon_and_previous_issue_is_used() -> None:
    calls: list[str] = []
    state = {"now": NOW}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params.get("base_time", request.url.params.get("tmFc", "")))
        if request.url.path.endswith("getVilageFcst"):
            if request.url.params["base_time"] == "0800":
                return httpx.Response(200, json={"response": {"header": {"resultCode": "03"}}})  # 아직 없음
            stamp = {"fcstDate": TOMORROW.strftime("%Y%m%d"), "fcstTime": "1000"}
            return _ok([{"category": "POP", "fcstValue": "20", **stamp}])
        return httpx.Response(200, json={"response": None})  # 예상 밖 모양

    weather = WeatherService(
        KmaClient("k", transport=httpx.MockTransport(handler)),
        WeatherSettings(_env_file=None),
        clock=lambda: state["now"].astimezone(UTC),
    )
    found = weather.forecast(35.15, 129.11, TOMORROW, 10)
    assert found is not None and found.pop == 20 and found.issued_at.hour == 5  # 08시 자료가 없어 05시 발표
    assert weather.forecast(35.15, 129.11, date(2026, 12, 8), 10) is None  # 중기 모양 오류 → 예보 없음
    assert weather.rain(35.15, 129.11, date(2026, 12, 8), 10) is None
    before = len(calls)
    state["now"] = NOW + timedelta(seconds=61)
    weather.forecast(35.15, 129.11, TOMORROW, 10)
    assert len(calls) > before  # 빈 결과는 1분 뒤 다시 조회한다


def test_mid_term_keys_count_days_from_the_issue_date() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getMidLandFcst"):
            return _ok(
                [{"rnSt5Am": 10, "rnSt5Pm": 40, "wf5Am": "맑음", "wf5Pm": "구름많음", "rnSt8": 70, "wf8": "흐리고 비"}]
            )
        return _ok([{"taMin5": 3, "taMax5": 11, "taMin8": 5, "taMax8": 9}])

    mid = KmaClient("k", transport=httpx.MockTransport(handler)).mid(datetime(2026, 11, 28, 18, tzinfo=KST))
    assert mid.days[date(2026, 12, 3)].sky_pm == "구름많음" and mid.days[date(2026, 12, 3)].pop_pm == 40
    assert mid.days[date(2026, 12, 6)].pop_am == 70 and mid.days[date(2026, 12, 6)].temp_max == 9
    assert date(2026, 12, 2) not in mid.days  # 18시 발표는 5일 뒤부터
