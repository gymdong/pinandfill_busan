from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.modules.ai.interpret import InterpretService, build_interpret_service
from app.modules.ai.settings import AISettings


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """개발자 PC 의 backend/.env 에 키가 있어도 테스트가 실제 LLM 을 부르지 않게 한다.

    서비스를 주입하지 않은 앱이 기본 서비스를 만들 때 키 없는 설정(규칙 해석만)을 쓰게 한다.
    """

    def rule_only() -> InterpretService:
        return build_interpret_service(AISettings(_env_file=None, api_key=None))

    monkeypatch.setattr("app.modules.trips.intake.build_interpret_service", rule_only)


@pytest.fixture(autouse=True)
def no_real_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """backend/.env 에 키가 있어도 기본 구성이 실제 카카오·TMAP·ODsay 를 부르지 않게 한다.

    환경변수가 .env 보다 우선하므로 빈 값으로 두면 기본 구성은 키가 없는 것으로 본다.
    """
    for name in ("KAKAO_REST_API_KEY", "TMAP_API_KEY", "ODSAY_API_KEY"):
        monkeypatch.setenv(name, "")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(Settings(app_name="Backend test"))) as test_client:
        yield test_client
