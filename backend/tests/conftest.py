"""시험 공통 픽스처.

`app.main` 은 import 될 때 모듈 수준 `app = create_app()` 으로 DB·장소 출처 설정을 읽는다. 그래서 아래 격리는
`app.main` 을 import 하기 전(이 파일 맨 위, 시험 수집 전)에 한 번 하고, 시험마다 autouse 픽스처로 다시 한다.
"""

import os
from collections.abc import Iterator

import pytest

from app.batch.settings import BatchSettings
from app.db.session import DatabaseSettings
from app.modules.places.source import PlaceSourceSettings

# 개발자 backend/.env·셸에 있어도 시험에 새지 않게 지우는 DB·장소 출처·배치 수집(키·웹훅) 환경변수
DB_ENV_NAMES = (
    "DATABASE_URL",
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
    "DB_POOL_TIMEOUT",
    "DB_LOCK_TIMEOUT_MS",
    "DB_STATEMENT_TIMEOUT_MS",
    "PLACE_DATA_SOURCE",
    "TOURAPI_SERVICE_KEY",
    "ADMIN_ALERT_WEBHOOK_URL",
    "BATCH_BACKOFF_BASE_MIN",
)
# 모두 env_ignore_empty 라 빈 환경변수로는 .env 값을 막을 수 없어 .env 읽기를 끈다.
DB_SETTINGS_CLASSES = (DatabaseSettings, PlaceSourceSettings, BatchSettings)

# 수집 단계 격리: 개발자 .env 에 PLACE_DATA_SOURCE=db 가 있어도 app.main import 가 개발 DB 를 읽거나 실패하지 않는다.
for _settings_class in DB_SETTINGS_CLASSES:
    _settings_class.model_config["env_file"] = None
for _name in DB_ENV_NAMES:
    os.environ.pop(_name, None)

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.ai.interpret import InterpretService, build_interpret_service  # noqa: E402
from app.modules.ai.settings import AISettings  # noqa: E402
from app.modules.ai.waypoint_reason import WaypointReasonService, build_waypoint_reason_service  # noqa: E402
from app.modules.recommend.mood import MoodService, build_mood_service  # noqa: E402
from app.modules.recommend.mood_data import MoodDataProvider  # noqa: E402


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """개발자 PC 의 backend/.env 에 키가 있어도 테스트가 실제 LLM 을 부르지 않게 한다.

    서비스를 주입하지 않은 앱이 기본 서비스를 만들 때 키 없는 설정(규칙 해석만)을 쓰게 한다.
    """

    def rule_only() -> InterpretService:
        return build_interpret_service(AISettings(_env_file=None, api_key=None))

    monkeypatch.setattr("app.modules.trips.intake.build_interpret_service", rule_only)

    def mood_rules_only(data: MoodDataProvider) -> MoodService:
        return build_mood_service(data, AISettings(_env_file=None, api_key=None))

    monkeypatch.setattr("app.modules.recommend.mood_router.build_mood_service", mood_rules_only)

    def reasons_rules_only() -> WaypointReasonService:
        return build_waypoint_reason_service(AISettings(_env_file=None, api_key=None))

    monkeypatch.setattr("app.modules.trips.router.build_waypoint_reason_service", reasons_rules_only)


def isolate_db_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """backend/.env 에 DATABASE_URL·PLACE_DATA_SOURCE 가 있어도 기본 구성은 메모리 저장소·CSV 장소를 쓰게 한다.

    두 설정은 env_ignore_empty 라 빈 환경변수는 .env 값으로 넘어간다(빈 값으로는 막을 수 없다).
    그래서 .env 읽기를 끄고 환경변수를 지운다. DB 시험은 TEST_DATABASE_URL 로 따로 돌고,
    .env 읽기 시험은 `_env_file=` 로 파일을 직접 넘긴다.
    """
    for settings_class in DB_SETTINGS_CLASSES:
        monkeypatch.setitem(settings_class.model_config, "env_file", None)
    for name in DB_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_real_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """backend/.env 에 키가 있어도 기본 구성이 실제 카카오·TMAP·ODsay·DB 를 쓰지 않게 한다.

    환경변수가 .env 보다 우선하므로 빈 값으로 두면 기본 구성은 키가 없는 것으로 본다.
    """
    for name in (
        "KAKAO_REST_API_KEY",
        "TMAP_API_KEY",
        "ODSAY_API_KEY",
    ):
        monkeypatch.setenv(name, "")
    isolate_db_settings(monkeypatch)
    # 혼잡 입력·설정 위치와 관리자 알림은 개발자 환경이 아니라 저장소 기본값을 쓴다(os.environ 만 읽는다).
    for name in ("CROWD_DATA_DIR", "CROWD_CONFIG_PATH", "ADMIN_ALERT_WEBHOOK_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(Settings(app_name="Backend test"))) as test_client:
        yield test_client
