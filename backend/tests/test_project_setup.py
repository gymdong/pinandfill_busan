import importlib
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "module",
    ["app.core", "app.db", "app.api", "app.modules.places", "app.modules.ai", "app.adapters.kakao"],
)
def test_app_packages_import(module: str) -> None:
    importlib.import_module(module)


def test_env_example_has_names_only() -> None:
    """키 이름만 두고 값은 비워 둔다. 실수로 실제 키를 넣으면 실패한다."""
    lines = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8").splitlines()
    entries = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    assert entries, ".env.example 에 키 이름이 없다"
    for entry in entries:
        name, sep, value = entry.partition("=")
        assert sep and name.strip(), f"형식 오류: {entry!r}"
        assert value.strip() == "", f"{name.strip()} 에 값이 들어 있다"
