"""FR-008 장소별 예상 혼잡도 조회 서비스."""

import logging
from datetime import date
from typing import Protocol

from .avoidance import AvoidanceSettings
from .schemas import PlaceCrowdResponse

logger = logging.getLogger(__name__)


class CrowdDataProvider(Protocol):
    """실제 혼잡도 데이터를 제공하는 객체의 인터페이스."""

    def find(
        self,
        place_id: str,
        on_date: date | None,
    ) -> PlaceCrowdResponse | None: ...


class CrowdService:
    """장소별 혼잡도 조회. 데이터가 없으면 정보 부족으로 응답한다."""

    def __init__(
        self,
        provider: CrowdDataProvider | None = None,
        *,
        avoidance: AvoidanceSettings | None = None,
    ) -> None:
        self._provider = provider
        # FR-009 배치 기준. 혼잡 계산과 같은 설정 파일에서 읽어 넘긴다(엔진 설정과 어긋나지 않게).
        self.avoidance = avoidance or AvoidanceSettings()

    def get(
        self,
        place_id: str,
        on_date: date | None = None,
    ) -> PlaceCrowdResponse:
        if self._provider is not None:
            result = self._provider.find(place_id, on_date)
            if result is not None:
                return result

        # 검증된 혼잡 데이터가 없으면 임의의 예측값을 만들지 않는다. 신호 0건은 로그로 남긴다(ERR-011).
        # 초기 일정 생성은 선택·날짜마다 부르므로 debug 로 남기고, 요청당 요약은 엔진이 info 로 남긴다.
        logger.debug("crowd_no_signal place=%r", place_id)
        return PlaceCrowdResponse(
            hours=[],
            confidence="없음",
            as_of=None,
            sources=[],
        )
