"""InputSanitizer: LLM 에 넘기기 전에 사용자 입력을 검증·정제한다(AI-REQ-07, SDD 7.4)."""

import re
import unicodedata


class InvalidInputError(Exception):
    """입력할 수 없는 내용. API 계층에서 ERR-001(400)로 바꾼다.

    reason: empty / too_long / blocked. 원문은 예외·로그에 담지 않는다.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# 지시문을 바꾸려는 흔한 표현. 이것만으로 주입을 막을 수는 없으므로 방어의 중심은
# (1) 입력을 지시문과 분리해 전달하고 (2) 출력을 스키마·값 검증으로 거르는 것이다.
_INJECTION_PATTERNS = re.compile(
    r"ignore\s+(all\s+|the\s+)?(previous|above|prior)"
    r"|system\s*prompt"
    r"|(이전|위|앞)\s*(의\s*)?(지시|명령|지침|프롬프트)"
    r"|(지시|명령|지침)\s*(문)?\s*(을|를)?\s*무시"
    r"|시스템\s*프롬프트"
    r"|프롬프트\s*(를|을)\s*(출력|공개|보여)",
    re.IGNORECASE,
)

_WHITESPACE = re.compile(r"\s+")


def sanitize(text: str, *, max_chars: int) -> str:
    """제어 문자와 구분 기호를 지우고 공백을 정리한다.

    Raises:
        InvalidInputError: 비어 있거나, 너무 길거나, 지시문 주입으로 보이는 입력.
    """
    # 유니코드 정규화로 전각 문자·조합형을 일반 형태로 맞춘다(전각 숫자 '１０' → '10').
    normalized = unicodedata.normalize("NFKC", text)
    # 제어·서식 문자(줄바꿈, 탭, 방향 전환 문자 등)는 공백으로 바꾼다.
    cleaned = "".join(" " if unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} else char for char in normalized)
    # 프롬프트에서 사용자 입력을 감싸는 구분 기호를 입력이 흉내 내지 못하게 한다.
    cleaned = cleaned.replace("<", " ").replace(">", " ")
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    if not cleaned:
        raise InvalidInputError("empty")
    if len(cleaned) > max_chars:
        raise InvalidInputError("too_long")
    if _INJECTION_PATTERNS.search(cleaned):
        raise InvalidInputError("blocked")
    return cleaned
