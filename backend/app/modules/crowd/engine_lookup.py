"""FR-009: 초기 일정 엔진(CrowdLookup)에 CrowdService 의 예상 혼잡을 넘긴다."""

from datetime import date

from app.modules.crowd.schemas import PlaceCrowdResponse
from app.modules.crowd.service import CrowdService
from app.modules.engine.schemas import PlaceRef, PublicPlaceRef


class CrowdServiceLookup:
    """공공 장소만 조회한다. 카카오 장소는 혼잡 근거가 없으므로 None 이다."""

    def __init__(self, service: CrowdService) -> None:
        self._service = service

    def crowd(self, place_ref: PlaceRef, *, on_date: date) -> PlaceCrowdResponse | None:
        if not isinstance(place_ref, PublicPlaceRef):
            return None
        return self._service.get(place_ref.place_id, on_date)
