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


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(Settings(app_name="Backend test"))) as test_client:
        yield test_client
