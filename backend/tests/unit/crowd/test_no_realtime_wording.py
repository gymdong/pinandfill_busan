"""FR-008: 예상 혼잡 쪽 코드·문서·응답 문자열에 금지 표현(FORBIDDEN, SRS FR-008)을 쓰지 않는다(A3-6 백엔드 절반).

다른 모듈(예: AI OutputGuard 의 금지어 목록)은 그 단어를 걸러 내려고 문자열로 갖고 있으므로 대상이 아니다.
"""

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]
REPO = BACKEND.parent
FORBIDDEN = "실" + "시간"


def test_crowd_sources_and_docs_have_no_forbidden_wording():
    paths = [
        *sorted((BACKEND / "app" / "modules" / "crowd").glob("*.py")),
        *sorted((REPO / "data" / "crowd").glob("*")),
        REPO / "data" / "seed" / "crowd" / "crowd_config.json",
        *sorted((BACKEND / "tests" / "fixtures" / "crowd").rglob("*")),
    ]
    offenders = [path.name for path in paths if path.is_file() and FORBIDDEN in path.read_text(encoding="utf-8")]
    assert offenders == []
