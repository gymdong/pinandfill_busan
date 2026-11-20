"""LLM 공급자 인터페이스(SDD 7.2 LlmProvider). 모델을 바꿔도 상위 로직이 바뀌지 않게 한다(NFR-009)."""

from typing import Protocol


class LlmError(Exception):
    """LLM 호출 실패. 호출한 쪽은 규칙 기반 처리로 대체한다(AI-REQ-05).

    reason: timeout / network / quota_exceeded / auth / http_status / invalid_response
    프롬프트·응답 본문은 담지 않는다.
    """

    def __init__(self, reason: str, status_code: int | None = None) -> None:
        super().__init__(reason if status_code is None else f"{reason} ({status_code})")
        self.reason = reason
        self.status_code = status_code


class LlmProvider(Protocol):
    async def generate_json(self, *, system: str, user: str, schema: dict[str, object]) -> object:
        """지시문(`system`)과 사용자 입력(`user`)을 분리해 보내고, `schema` 형식의 JSON 을 파싱해 돌려준다.

        Raises:
            LlmError: 호출이 실패했거나 응답이 JSON 이 아닐 때.
        """
        ...
