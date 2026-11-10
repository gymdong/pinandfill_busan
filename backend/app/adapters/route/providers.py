"""Documented HTTP route lookups. No raw response, coordinate cache or request logging."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from math import ceil, isfinite
from typing import Any, Literal

from pydantic import AwareDatetime, Field, SecretStr

from app.adapters.route.quota import CallBudget
from app.adapters.route.transport import RouteTransport, TransportError
from app.modules.engine.schemas import ContractModel, RouteTimeSemantics, TransientPlaceDetails

Mode = Literal["TRANSIT", "CAR", "WALK"]
Source = Literal["TMAP", "ODSAY"]
Failure = Literal[
    "invalid_input",
    "unsupported_mode",
    "unsupported_departure",
    "missing_key",
    "quota",
    "timeout",
    "network",
    "authentication",
    "upstream",
    "invalid_response",
    "no_route",
]


def utc_now() -> datetime:
    return datetime.now(UTC)


class RouteQuery(ContractModel):
    origin: TransientPlaceDetails = Field(exclude=True, repr=False)
    destination: TransientPlaceDetails = Field(exclude=True, repr=False)
    mode: Mode
    departure_at: AwareDatetime | None = None
    allow_time_context: bool = False

    def valid_coordinates(self) -> bool:
        # Recheck even objects built via model_copy/model_construct at an integration boundary.
        for place in (self.origin, self.destination):
            for coordinate, limit in ((place.lat, 90), (place.lng, 180)):
                if (
                    isinstance(coordinate, bool)
                    or not isinstance(coordinate, (int, float))
                    or not -limit <= coordinate <= limit
                    or not isfinite(coordinate)
                ):
                    return False
        return True


@dataclass(frozen=True)
class LookupResult:
    provider: Source
    duration_min: int | None
    computed_at: datetime
    failure: Failure | None = None
    departure_applied: bool = False
    time_semantics: RouteTimeSemantics = "unspecified"


@dataclass(frozen=True)
class ProviderSettings:
    api_key: SecretStr = field(repr=False)
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("Route timeout must be finite and positive")


def _duration(value: object, *, seconds: bool) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not isfinite(value) or value < 0:
        return None
    return ceil(value / 60 if seconds else value)


class HTTPRouteAdapter:
    name: Source

    def __init__(
        self,
        transport: RouteTransport,
        settings: ProviderSettings,
        budget: CallBudget,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.transport = transport
        self.settings = settings
        self.budget = budget
        self.clock = clock

    def failed(self, reason: Failure) -> LookupResult:
        return LookupResult(self.name, None, self.clock(), reason)

    def _post(
        self, url: str, body: dict[str, Any], *, encoding: Literal["json", "form"]
    ) -> dict[str, Any] | LookupResult:
        key = self.settings.api_key.get_secret_value()
        if not key:
            return self.failed("missing_key")
        if not self.budget.allow():
            return self.failed("quota")
        headers = {"Accept": "application/json", "Cache-Control": "no-store"}
        if self.name == "TMAP":
            headers["appKey"] = key
        else:
            body = {**body, "apiKey": key}
        try:
            reply = self.transport.post(
                url,
                headers=headers,
                body=body,
                encoding=encoding,
                timeout=self.settings.timeout_seconds,
            )
        except TransportError as exc:
            return self.failed(exc.kind)
        except Exception:
            # Third-party transports must not expose payload-bearing exceptions.
            return self.failed("network")
        if reply.status in (401, 403):
            return self.failed("authentication")
        if reply.status == 429:
            self.budget.pause(reply.retry_after if reply.retry_after is not None else 60.0)
            return self.failed("quota")
        if not 200 <= reply.status < 300:
            return self.failed("upstream")
        if "error" in reply.body:
            # Inspect the known authentication marker only; never retain the message.
            errors = reply.body["error"]
            entries = errors if isinstance(errors, list) else [errors]
            if any(isinstance(item, dict) and "ApiKeyAuthFailed" in str(item.get("message", "")) for item in entries):
                return self.failed("authentication")
            return self.failed("upstream")
        return reply.body


class TMAPAdapter(HTTPRouteAdapter):
    name: Source = "TMAP"

    def lookup(self, query: RouteQuery) -> LookupResult:
        if query.mode not in ("TRANSIT", "CAR", "WALK"):
            return self.failed("unsupported_mode")
        if not query.valid_coordinates():
            return self.failed("invalid_input")
        if query.departure_at is not None and query.mode != "CAR" and not query.allow_time_context:
            # searchDttm only documents service availability, not a departure-specific duration.
            return self.failed("unsupported_departure")
        origin, destination = query.origin, query.destination
        body: dict[str, Any] = {
            "startX": origin.lng,
            "startY": origin.lat,
            "endX": destination.lng,
            "endY": destination.lat,
        }
        if query.mode == "TRANSIT":
            body = {key: str(value) for key, value in body.items()}
            body.update(count=10, lang=0, format="json")
            if query.departure_at is not None:
                if query.departure_at.second or query.departure_at.microsecond:
                    return self.failed("unsupported_departure")
                body["searchDttm"] = query.departure_at.astimezone(timezone(timedelta(hours=9))).strftime("%Y%m%d%H%M")
            url = "https://apis.openapi.sk.com/transit/routes"
        elif query.departure_at is not None and query.mode == "CAR":
            body = {
                "routesInfo": {
                    "departure": {"name": "origin", "lon": origin.lng, "lat": origin.lat},
                    "destination": {
                        "name": "destination",
                        "lon": destination.lng,
                        "lat": destination.lat,
                    },
                    "predictionType": "departure",
                    "predictionTime": query.departure_at.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "searchOption": "00",
                    "tollgateCarType": "car",
                    "trafficInfo": "N",
                }
            }
            url = "https://apis.openapi.sk.com/tmap/routes/prediction?version=1"
        else:
            body.update(reqCoordType="WGS84GEO", resCoordType="WGS84GEO")
            if query.mode == "WALK":
                # Required generic labels, never a Kakao name.
                body.update(startName="origin", endName="destination")
                url = "https://apis.openapi.sk.com/tmap/routes/pedestrian?version=1"
            else:
                url = "https://apis.openapi.sk.com/tmap/routes?version=1"
        payload = self._post(url, body, encoding="json")
        if isinstance(payload, LookupResult):
            return payload
        try:
            if query.mode == "TRANSIT":
                itineraries = payload["metaData"]["plan"]["itineraries"]
                if not isinstance(itineraries, list):
                    return self.failed("invalid_response")
                durations = []
                for route in itineraries:
                    legs = route["legs"]
                    if not isinstance(legs, list) or not legs:
                        continue
                    if any(leg.get("service") == 0 for leg in legs):
                        continue
                    value = _duration(route.get("totalTime"), seconds=True)
                    if value is not None:
                        durations.append(value)
            else:
                features = payload["features"]
                if not isinstance(features, list):
                    return self.failed("invalid_response")
                durations = [
                    value
                    for feature in features
                    if (value := _duration(feature["properties"].get("totalTime"), seconds=True)) is not None
                ]
            if not durations:
                return self.failed("no_route")
            return LookupResult(
                self.name,
                min(durations),
                self.clock(),
                departure_applied=query.departure_at is not None and query.mode != "WALK",
                time_semantics=(
                    "prediction"
                    if query.mode == "CAR" and query.departure_at is not None
                    else "service_availability"
                    if query.mode == "TRANSIT" and query.departure_at is not None
                    else "static"
                ),
            )
        except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
            return self.failed("invalid_response")


class ODsayAdapter(HTTPRouteAdapter):
    """maasRP: explicit minute units and departure input. CAR is not supported.

    Vendor timezone is not stated in the public reference: the integrator must
    supply a confirmed search timezone instead of silently assuming UTC or KST.
    """

    name: Source = "ODSAY"

    def __init__(
        self,
        transport: RouteTransport,
        settings: ProviderSettings,
        budget: CallBudget,
        *,
        search_timezone: tzinfo,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        super().__init__(transport, settings, budget, clock=clock)
        self.search_timezone = search_timezone

    def lookup(self, query: RouteQuery) -> LookupResult:
        if query.mode not in ("TRANSIT", "WALK"):
            return self.failed("unsupported_mode")
        if not query.valid_coordinates():
            return self.failed("invalid_input")
        departure = query.departure_at or self.clock()
        if departure.utcoffset() is None:
            return self.failed("invalid_input")
        if query.departure_at is not None and (departure.second or departure.microsecond):
            return self.failed("unsupported_departure")
        method = 2 if query.mode == "TRANSIT" else 1
        payload = self._post(
            "https://api.odsay.com/v1/api/maasRP",
            {
                "SX": query.origin.lng,
                "SY": query.origin.lat,
                "EX": query.destination.lng,
                "EY": query.destination.lat,
                "SearchTime": departure.astimezone(self.search_timezone).strftime("%Y%m%d%H%M"),
                "SearchMethod": str(method),
                "output": "json",
            },
            encoding="form",
        )
        if isinstance(payload, LookupResult):
            return payload
        try:
            paths = payload["result"]["paths"]
            if not isinstance(paths, list):
                return self.failed("invalid_response")
            durations = [
                value
                for path in paths
                if path["pathType"] == method
                if (value := _duration(path.get("totalTime"), seconds=False)) is not None
            ]
            if not durations:
                return self.failed("no_route")
            return LookupResult(
                self.name,
                min(durations),
                self.clock(),
                departure_applied=query.departure_at is not None,
                time_semantics="search_context",
            )
        except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
            return self.failed("invalid_response")
