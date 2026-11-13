from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol

from .geo import distance_m
from .schemas import PublicPlace


class PublicPlaceRepository(Protocol):
    """공공 DB 장소 조회. 실제 DB 구현은 places·place_match_overrides 테이블이 준비되면 추가한다."""

    def find_by_kakao_id(self, kakao_place_id: str) -> PublicPlace | None:
        """수동 매칭표에 등록된 카카오 장소 ID 의 공공 DB 장소"""
        ...

    def find_near(self, lat: float, lng: float, radius_m: float) -> Sequence[PublicPlace]:
        """좌표에서 반경 안에 있는 공공 DB 장소"""
        ...


class InMemoryPublicPlaceRepository:
    """테스트용 메모리 구현. 운영 DB 나 공유 캐시가 아니다."""

    def __init__(self, places: Iterable[PublicPlace], kakao_overrides: Mapping[str, str] | None = None) -> None:
        self._places = {place.id: place for place in places}
        # 카카오 장소 ID → 공공 DB 장소 ID (수동 매칭표)
        self._kakao_overrides = dict(kakao_overrides or {})

    def find_by_kakao_id(self, kakao_place_id: str) -> PublicPlace | None:
        place_id = self._kakao_overrides.get(kakao_place_id)
        return self._places.get(place_id) if place_id is not None else None

    def find_near(self, lat: float, lng: float, radius_m: float) -> Sequence[PublicPlace]:
        return [place for place in self._places.values() if distance_m(lat, lng, place.lat, place.lng) <= radius_m]
