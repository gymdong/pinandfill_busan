"""Legacy engine bridge plus an explicit departure-aware lookup boundary."""

from collections.abc import Callable
from datetime import datetime

from pydantic import SecretStr, ValidationError

from app.adapters.route.providers import (
    SEOUL_TIMEZONE,
    LookupResult,
    Mode,
    ODsayAdapter,
    ProviderSettings,
    RouteQuery,
    TMAPAdapter,
    utc_now,
)
from app.adapters.route.quota import CallBudget
from app.adapters.route.settings import ODsaySettings, TMAPSettings
from app.adapters.route.transport import SafeHTTPTransport
from app.modules.engine.interfaces import RouteEstimate, RouteProvider
from app.modules.engine.schemas import TransientPlaceDetails


class LiveRouteProvider:
    def __init__(
        self,
        primary: TMAPAdapter,
        fallback: ODsayAdapter | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.clock = clock

    def lookup(
        self,
        origin: TransientPlaceDetails,
        destination: TransientPlaceDetails,
        *,
        mode: Mode,
        departure_at: datetime | None = None,
        allow_time_context: bool = False,
    ) -> LookupResult:
        try:
            query = RouteQuery(
                origin=origin,
                destination=destination,
                mode=mode,
                departure_at=departure_at,
                allow_time_context=allow_time_context,
            )
        except ValidationError:
            return LookupResult(self.primary.name, None, self.clock(), "invalid_input")
        if not query.valid_coordinates():
            return LookupResult(self.primary.name, None, self.clock(), "invalid_input")
        result = self.primary.lookup(query)
        if result.duration_min is None and self.fallback is not None and mode in ("TRANSIT", "WALK"):
            result = self.fallback.lookup(query)
        return result

    def estimate(
        self, origin: TransientPlaceDetails, destination: TransientPlaceDetails, *, mode: Mode
    ) -> RouteEstimate:
        # Legacy callers retain the untimed protocol. Engine code uses estimate_at.
        result = self.lookup(origin, destination, mode=mode)
        # Diagnostic LookupResult.provider records the attempted supplier; it is
        # never a confirmed source when no duration was obtained.
        return RouteEstimate(
            result.duration_min,
            result.provider if result.duration_min is not None and result.failure is None else "UNKNOWN",
            result.computed_at,
            time_semantics=result.time_semantics,
            lookup_failed=result.failure is not None,
        )

    def estimate_at(
        self,
        origin: TransientPlaceDetails,
        destination: TransientPlaceDetails,
        *,
        mode: Mode,
        departure_at: datetime,
    ) -> RouteEstimate:
        # This entry point must never use lookup's legacy current-time fallback.
        if departure_at is None or departure_at.utcoffset() is None:
            return RouteEstimate(None, "UNKNOWN", self.clock(), lookup_failed=True)
        result = self.lookup(origin, destination, mode=mode, departure_at=departure_at, allow_time_context=True)
        return RouteEstimate(
            result.duration_min,
            result.provider if result.duration_min is not None and result.failure is None else "UNKNOWN",
            result.computed_at,
            time_semantics=result.time_semantics,
            lookup_failed=result.failure is not None,
        )


class UnconfiguredRouteProvider:
    """경로 키가 없을 때. 조회하지 않고 이동시간을 만들지 않는다(엔진이 '이동시간 확인 필요'로 표시)."""

    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock

    def estimate(
        self, origin: TransientPlaceDetails, destination: TransientPlaceDetails, *, mode: Mode
    ) -> RouteEstimate:
        return RouteEstimate(None, "UNKNOWN", self.clock())


def build_route_provider(tmap: TMAPSettings | None = None, odsay: ODsaySettings | None = None) -> RouteProvider:
    """키가 있으면 TMAP 주력·ODsay 예비, 둘 다 없으면 조회하지 않는다. 만들 때 네트워크를 쓰지 않는다."""
    tmap = tmap if tmap is not None else TMAPSettings()
    odsay = odsay if odsay is not None else ODsaySettings()
    tmap_key, odsay_key = tmap.api_key, odsay.api_key
    if tmap_key is None and odsay_key is None:
        return UnconfiguredRouteProvider()
    transport = SafeHTTPTransport()
    # TMAP 키가 없으면 TMAP 은 호출 없이 missing_key 로 끝나고 ODsay 로 넘어간다.
    primary = TMAPAdapter(
        transport,
        ProviderSettings(tmap_key or SecretStr(""), tmap.timeout_seconds),
        CallBudget(tmap.daily_call_limit),
    )
    fallback = None
    if odsay_key is not None:
        # ODsay 검색 시각의 시간대는 공식 문서에 없다. 국내 서비스라 한국 시간으로 가정한다(확인 필요).
        fallback = ODsayAdapter(
            transport,
            ProviderSettings(odsay_key, odsay.timeout_seconds),
            CallBudget(odsay.daily_call_limit),
            search_timezone=SEOUL_TIMEZONE,
        )
    return LiveRouteProvider(primary, fallback)
