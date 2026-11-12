"""Legacy engine bridge plus an explicit departure-aware lookup boundary."""

from collections.abc import Callable
from datetime import datetime

from pydantic import ValidationError

from app.adapters.route.providers import (
    LookupResult,
    Mode,
    ODsayAdapter,
    RouteQuery,
    TMAPAdapter,
    utc_now,
)
from app.modules.engine.interfaces import RouteEstimate
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
