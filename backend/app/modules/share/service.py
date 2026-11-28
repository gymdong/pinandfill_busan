"""FR-011 읽기 전용 공유(API-019·020).

- 토큰은 `secrets.token_urlsafe(32)`(256비트)로 만들고, 저장소에는 해시만 남긴다(추측 불가, SDD 보안).
- 공유 응답에는 여행 ID 를 넣지 않는다. 지금 편집 API 는 여행 ID 만 알면 호출할 수 있으므로,
  ID 가 새면 읽기 전용이 아니게 된다. 일정은 저장된 것을 다시 계산하지 않고 투영만 한다(경로 조회 없음).
"""

import secrets
from collections.abc import Callable
from datetime import UTC, datetime

from app.modules.share.repository import ShareLinkRepository, token_digest
from app.modules.share.schemas import SharedTripConditions, SharedTripResponse, ShareTripRequest, ShareTripResponse
from app.modules.trips.service import TripNotFoundError, TripService


class SharedLinkNotFoundError(Exception):
    """없거나 만료된 링크. 둘을 구분해 알리지 않는다(ERR-016, 404)."""


class InvalidExpiryError(ValueError):
    """만료 시각이 지금보다 앞이다."""


def _now() -> datetime:
    return datetime.now(UTC)


class ShareService:
    def __init__(self, links: ShareLinkRepository, trips: TripService, *, clock: Callable[[], datetime] = _now) -> None:
        self.links = links
        self.trips = trips
        self.clock = clock

    def share(self, trip_id: str, request: ShareTripRequest) -> ShareTripResponse:
        expires_at = request.expires_at
        if expires_at is not None and expires_at <= self.clock():
            raise InvalidExpiryError
        # 없는 여행에는 링크를 만들지 않는다(TripNotFoundError → 404).
        self.trips.detail(trip_id)
        token = secrets.token_urlsafe(32)
        self.links.create(trip_id, token_digest(token), expires_at)
        return ShareTripResponse(url=f"/shared/{token}", token=token, expires_at=expires_at)

    def shared(self, token: str) -> SharedTripResponse:
        link = self.links.find(token_digest(token))
        if link is None or (link.expires_at is not None and link.expires_at <= self.clock()):
            raise SharedLinkNotFoundError
        try:
            detail = self.trips.detail(link.trip_id)
        except TripNotFoundError:
            raise SharedLinkNotFoundError from None
        trip = detail.trip
        return SharedTripResponse(
            trip=SharedTripConditions(dates=trip.dates, day_start=trip.day_start, day_end=trip.day_end, mode=trip.mode),
            schedule=detail.schedule,
        )
