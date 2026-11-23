
"""FR-008 장소별 예상 혼잡도 조회 서비스."""

from datetime import date
from typing import Protocol

from .schemas import PlaceCrowdResponse


class CrowdDataProvider(Protocol):
    """실제 혼잡도 데이터를 제공하는 객체의 인터페이스."""

    def find(
        self,
        place_id: str,
        on_date: date | None,
    ) -> PlaceCrowdResponse | None:
        ...


class CrowdService:
    """장소별 혼잡도 조회. 데이터가 없으면 정보 부족으로 응답한다."""

    def __init__(
        self,
        provider: CrowdDataProvider | None = None,
    ) -> None:
        self._provider = provider

    def get(
        self,
        place_id: str,
        on_date: date | None = None,
    ) -> PlaceCrowdResponse:
        if self._provider is not None:
            result = self._provider.find(place_id, on_date)
            if result is not None:
                return result

        # 검증된 혼잡 데이터가 없으면 임의의 예측값을 만들지 않는다.
        return PlaceCrowdResponse(
            hours=[],
            confidence="없음",
            as_of=None,
            sources=[],
        )
