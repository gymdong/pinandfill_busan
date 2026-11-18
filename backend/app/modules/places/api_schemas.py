"""API-003 응답 형식. 프런트 `PlaceSearchItem`(frontend/src/types/api.ts)과 필드가 같다."""

from pydantic import Field

from app.modules.engine.schemas import ContractModel

from .schemas import HoursStatus, PlaceBadge


class Coords(ContractModel):
    lat: float = Field(repr=False)
    lng: float = Field(repr=False)


class PlaceSearchItem(ContractModel):
    """검색 결과 1건. 이름·좌표·주소는 카카오 응답 값이라 응답으로만 내보내고 저장하지 않는다(D6)."""

    # 공공 DB 와 매칭되면 places.id, 아니면 null
    place_id: str | None
    kakao_place_id: str
    # 블록 추가(API-006)에 그대로 쓸 수 있는 표준 형식
    place_url: str
    name: str = Field(repr=False)
    coords: Coords
    category: str | None
    address: str | None = Field(repr=False)
    badge: PlaceBadge
    hours_status: HoursStatus


class PlaceSearchResponse(ContractModel):
    places: tuple[PlaceSearchItem, ...] = ()
