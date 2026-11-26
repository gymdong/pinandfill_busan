"""PLACE_DATA_SOURCE=csv|db 읽기 경로(FR-016). DB 를 CSV 로 시드하면 두 경로의 응답이 같아야 한다.

SQLite(alembic)는 항상, PostgreSQL 은 TEST_DATABASE_URL 이 있을 때 돈다. 외부 API 는 부르지 않는다(카카오는 가짜).
"""

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.kakao import KakaoPlace
from app.batch import cli
from app.db.session import Database, DatabaseSettings
from app.main import create_app
from app.modules.engine.schemas import PublicPlaceRef
from app.modules.places.samples import SamplePlaceData, load_kakao_overrides, load_sample_places
from app.modules.places.source import PlaceSourceError, PlaceSourceSettings
from app.modules.recommend.mood_data import load_theme_tags
from app.modules.trips.repository import FakeTripRepository
from app.modules.trips.schemas import KakaoPlaceKey, PublicPlaceInput
from tests.conftest import isolate_db_settings
from tests.integration.test_db_persistence import DB_KINDS, open_database, upgrade

BACKEND_DIR = Path(__file__).resolve().parents[2]
CROWD_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "crowd"
# 월요일부터 7일: 요일별 영업시간을 모두 본다.
WEEK = [date(2026, 11, 23) + timedelta(days=offset) for offset in range(7)]
SAMPLES = load_sample_places().all()


@pytest.fixture(params=DB_KINDS)
def database(request: pytest.FixtureRequest) -> Iterator[Database]:
    database = open_database(request.param)
    upgrade(database)
    yield database
    database.dispose()


class FakeKakao:
    """표본 장소마다 매칭표 ID 결과와, 매칭표에 없는 ID(이름·좌표로 매칭)의 결과를 돌려준다."""

    def __init__(self, *_: object) -> None:
        mapped = {public_id: kakao_id for kakao_id, public_id in load_kakao_overrides().items()}
        self.places = []
        for index, item in enumerate(SAMPLES):
            place = item.place
            ids = [f"90000{index:04d}", *([mapped[place.id]] if place.id in mapped else [])]
            self.places += [
                KakaoPlace(
                    kakao_place_id=kakao_id,
                    name=place.name,
                    lat=place.lat,
                    lng=place.lng,
                    place_url=f"http://place.map.kakao.com/{kakao_id}",
                    category_name="여행 > 관광명소",
                )
                for kakao_id in ids
            ]

    async def search_keyword(self, query: str, *, category_group_code: str | None = None) -> list[KakaoPlace]:
        return self.places


def responses(application: FastAPI) -> dict[str, Any]:
    """API-005 상세·API-012 혼잡·API-003 검색·API-013 분위기 추천 응답(모든 표본 장소, 모든 태그)."""
    result: dict[str, Any] = {}
    with TestClient(application) as client:
        for item in SAMPLES:
            place_id = item.place.id
            result[f"detail:{place_id}"] = client.get(f"/api/places/{place_id}").json()
            for day in WEEK:
                crowd = client.get(f"/api/places/{place_id}/crowd", params={"date": day.isoformat()})
                result[f"crowd:{place_id}:{day}"] = crowd.json()
        result["search"] = client.get("/api/places/search", params={"q": "부산"}).json()
        for tag in load_theme_tags():
            body = {"tags": [tag.code], "date": "2026-11-28", "limit": 20}
            result[f"mood:{tag.code}"] = client.post("/api/recommend/mood", json=body).json()
    return result


def provider_outputs(places: SamplePlaceData) -> dict[str, Any]:
    """엔진 PlaceDataProvider(get)·체류시간(stay_min) 출력. 카카오는 매칭표 ID 와 모르는 ID 를 본다."""
    result: dict[str, Any] = {}
    for item in SAMPLES:
        place_id = item.place.id
        for day in WEEK:
            result[f"get:{place_id}:{day}"] = places.get(PublicPlaceRef(place_id=place_id), on_date=day)
        result[f"stay:{place_id}"] = places.stay_min(PublicPlaceInput(place_id=place_id))
    for kakao_id in [*load_kakao_overrides(), "900000009"]:
        key = KakaoPlaceKey(kakao_place_id=kakao_id, place_url=f"https://place.map.kakao.com/{kakao_id}")
        result[f"stay:kakao:{kakao_id}"] = places.stay_min(key)
    return result


def app_for(source: str, monkeypatch: pytest.MonkeyPatch, database: Database | None) -> FastAPI:
    monkeypatch.setenv("PLACE_DATA_SOURCE", source)
    monkeypatch.setattr("app.main.default_database", lambda: database)
    return create_app()


def test_db_mode_matches_csv_mode_for_every_sample_place(database: Database, monkeypatch: pytest.MonkeyPatch):
    assert SAMPLES and any(item.hours for item in SAMPLES) and any(item.address for item in SAMPLES)
    cli.seed_places(database)
    monkeypatch.setenv("KAKAO_REST_API_KEY", "test-rest-key")
    monkeypatch.setattr("app.main.KakaoLocalAdapter", FakeKakao)
    # 혼잡은 시험용 입력으로 계산해 장소 주소 → 구·군 날짜 배수까지 거치게 한다.
    monkeypatch.setenv("CROWD_DATA_DIR", str(CROWD_FIXTURES))

    csv_app = app_for("csv", monkeypatch, None)
    db_app = app_for("db", monkeypatch, database)

    assert sorted(db_app.state.places.all(), key=lambda item: item.place.id) == sorted(
        csv_app.state.places.all(), key=lambda item: item.place.id
    )
    assert provider_outputs(db_app.state.places) == provider_outputs(csv_app.state.places)
    csv_responses = responses(csv_app)
    db_responses = responses(db_app)
    # 비교가 빈 응답끼리가 아닌지 확인한다.
    assert all(csv_responses[f"detail:{item.place.id}"]["place"]["id"] == item.place.id for item in SAMPLES)
    assert any(body["confidence"] != "없음" for key, body in csv_responses.items() if key.startswith("crowd:"))
    matched = {item["placeId"] for item in csv_responses["search"]["places"]}
    assert matched >= {item.place.id for item in SAMPLES} and any(
        body["places"] for key, body in csv_responses.items() if key.startswith("mood:")
    )
    assert db_responses == csv_responses


def test_trips_and_places_share_one_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite:///{tmp_path / 'app.db'}"
    seeded = Database(url)
    upgrade(seeded)
    cli.seed_places(seeded)
    seeded.dispose()
    created: list[Database] = []

    class RecordingDatabase(Database):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr("app.main.Database", RecordingDatabase)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("PLACE_DATA_SOURCE", "db")

    application = create_app()

    assert len(created) == 1
    assert application.state.trip_service.repository.database is created[0]
    assert {item.place.id for item in application.state.places.all()} == {item.place.id for item in SAMPLES}
    trip = {"dates": {"start": "2026-11-17", "end": "2026-11-17"}, "dayStart": "09:00", "dayEnd": "20:00"}
    block = {"dayNo": 1, "place": {"placeId": "130166"}, "isFixed": False, "origin": "USER"}
    disposed: list[Database] = []
    monkeypatch.setattr(RecordingDatabase, "dispose", lambda self: disposed.append(self))
    with TestClient(application) as client:
        trip_id = client.post("/api/trips", json={**trip, "mode": "TRANSIT"}).json()["tripId"]
        added = client.post(f"/api/trips/{trip_id}/blocks", json=block)
        assert disposed == []
    assert added.status_code == 200
    # 체류시간은 DB 의 default_stay_min 이다.
    assert added.json()["schedule"]["days"][0]["blocks"][0]["stayMin"] == 90
    # 앱이 끝나면 공유 연결 풀을 닫는다.
    assert disposed == created
    Database.dispose(created[0])


def test_db_mode_without_database_url_fails_at_startup(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PLACE_DATA_SOURCE", "db")
    with pytest.raises(PlaceSourceError, match="requires DATABASE_URL"):
        create_app()


def test_db_mode_with_empty_places_fails_at_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite:///{tmp_path / 'empty.db'}"
    empty = Database(url)
    upgrade(empty)
    empty.dispose()
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("PLACE_DATA_SOURCE", "db")
    disposed: list[Database] = []
    dispose = Database.dispose
    monkeypatch.setattr(Database, "dispose", lambda self: (disposed.append(self), dispose(self)))
    with pytest.raises(PlaceSourceError, match="places table is empty"):
        create_app()
    # 시작이 실패해도 만든 연결 풀을 닫는다.
    assert len(disposed) == 1


@pytest.mark.parametrize("value", [None, "", "csv"])
def test_csv_is_the_default_source(value: str | None, monkeypatch: pytest.MonkeyPatch):
    if value is None:
        monkeypatch.delenv("PLACE_DATA_SOURCE", raising=False)
    else:
        monkeypatch.setenv("PLACE_DATA_SOURCE", value)
    assert PlaceSourceSettings(_env_file=None).place_data_source == "csv"


def test_default_app_reads_csv_without_touching_the_database(monkeypatch: pytest.MonkeyPatch):
    # conftest 가 PLACE_DATA_SOURCE=csv 로 둔다. DB 가 있어도 장소는 CSV 에서 읽는다(places 테이블을 읽지 않는다).
    monkeypatch.setattr("app.modules.places.source.SqlPlaceStore", None)
    application = create_app()
    assert application.state.places.all() == SAMPLES


def test_unknown_source_fails_at_startup(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PLACE_DATA_SOURCE", "postgres")
    with pytest.raises(ValueError):
        create_app()


def test_tests_do_not_read_database_settings_from_the_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # 실제 backend/.env 는 읽지 않는다. 임시 .env 를 backend/.env 자리(설정의 env_file)에 둔다.
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE_URL=sqlite:///{tmp_path / 'leak.db'}\nPLACE_DATA_SOURCE=db\n", encoding="utf-8")
    for settings_class in (DatabaseSettings, PlaceSourceSettings):
        monkeypatch.setitem(settings_class.model_config, "env_file", env_file)
    # 예전 방식(빈 환경변수)으로는 .env 값이 그대로 쓰인다(#64 리뷰에서 재현한 누수).
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("PLACE_DATA_SOURCE", "")
    assert DatabaseSettings().url() is not None
    assert PlaceSourceSettings().place_data_source == "db"

    isolate_db_settings(monkeypatch)

    assert DatabaseSettings().url() is None
    assert PlaceSourceSettings().place_data_source == "csv"
    application = create_app()
    assert isinstance(application.state.trip_service.repository, FakeTripRepository)
    assert not (tmp_path / "leak.db").exists()
    # 파일을 직접 넘기는 .env 읽기 시험은 그대로 된다.
    assert DatabaseSettings(_env_file=env_file).url() is not None  # type: ignore[call-arg]


# backend/.env 자리(설정의 env_file)를 임시 .env 로 바꾼 뒤 argv[2:] 를 실행한다. 실제 backend/.env 는 읽지 않는다.
DEV_ENV_RUNNER = """
import runpy, sys
from app.db.session import DatabaseSettings
from app.modules.places.source import PlaceSourceSettings
for settings_class in (DatabaseSettings, PlaceSourceSettings):
    settings_class.model_config["env_file"] = sys.argv[1]
assert PlaceSourceSettings().place_data_source == "db" and DatabaseSettings().url()
if sys.argv[2] == "pytest":
    import pytest
    sys.exit(pytest.main(sys.argv[3:]))
import app.main
"""


def run_with_dev_env(env_file: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {name: value for name, value in os.environ.items() if name not in ("DATABASE_URL", "PLACE_DATA_SOURCE")}
    return subprocess.run(
        [sys.executable, "-c", DEV_ENV_RUNNER, str(env_file), *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_collection_ignores_a_developer_env_with_db_source(tmp_path: Path):
    # 개발자 .env: PLACE_DATA_SOURCE=db + 장소가 없는 DB. app.main 의 모듈 수준 create_app() 이 실패하는 구성이다.
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE_URL=sqlite:///{tmp_path / 'dev.db'}\nPLACE_DATA_SOURCE=db\n", encoding="utf-8")

    # 대조: 격리 없이 app.main 을 import 하면 실패한다.
    control = run_with_dev_env(env_file, "import")
    assert control.returncode != 0 and "no such table: places" in control.stderr

    collected = run_with_dev_env(
        env_file, "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests/test_project_setup.py"
    )
    assert collected.returncode == 0, collected.stdout + collected.stderr
    assert "tests/test_project_setup.py" in collected.stdout
