"""Small HTTPS boundary that never logs or retains route coordinates and keys."""

from __future__ import annotations

import http.client
import json
import math
import os
import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal, Protocol
from urllib.parse import urlencode, urlsplit

import certifi

from app.adapters.route.quota import MAX_PAUSE_SECONDS

_ALLOWED_HOSTS = frozenset({"apis.openapi.sk.com", "api.odsay.com"})
_TMAP_VERSIONED_PATHS = frozenset({"/tmap/routes", "/tmap/routes/pedestrian", "/tmap/routes/prediction"})
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def build_tls_context(environ: Mapping[str, str] | None = None) -> ssl.SSLContext:
    """카카오·Gemini 가 쓰는 httpx 와 같은 순서로 신뢰 저장소를 고른다. 검증 자체는 끄지 않는다.

    Python 기본 저장소는 배포판마다 달라(uv 가 설치한 macOS Python 은 TMAP 체인을 검증하지 못했다)
    기본은 certifi 를 쓰고, 사내 프록시처럼 SSL_CERT_FILE·SSL_CERT_DIR 을 둔 환경은 그 값을 따른다.
    """
    env = os.environ if environ is None else environ
    if env.get("SSL_CERT_FILE"):
        return ssl.create_default_context(cafile=env["SSL_CERT_FILE"])
    if env.get("SSL_CERT_DIR"):
        return ssl.create_default_context(capath=env["SSL_CERT_DIR"])
    return ssl.create_default_context(cafile=certifi.where())


_TLS_CONTEXT = build_tls_context()


class TransportError(Exception):
    """Sanitized failure classification without request or upstream details."""

    def __init__(self, kind: Literal["timeout", "network", "invalid_response"]) -> None:
        self.kind = kind
        super().__init__(kind)


@dataclass(frozen=True, slots=True)
class HttpReply:
    status: int
    body: dict[str, Any] = field(repr=False)
    retry_after: float | None = None


class RouteTransport(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any],
        encoding: Literal["json", "form"],
        timeout: float,
    ) -> HttpReply: ...


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=UTC)
            seconds = (target - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, MAX_PAUSE_SECONDS)


class SafeHTTPTransport:
    """Direct HTTPS only: no redirects, proxy environment, retries, or logging."""

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any],
        encoding: Literal["json", "form"],
        timeout: float,
    ) -> HttpReply:
        if not math.isfinite(timeout) or timeout <= 0:
            raise TransportError("invalid_response")
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            raise TransportError("invalid_response") from None
        query_allowed = (
            parsed.hostname == "apis.openapi.sk.com"
            and parsed.path in _TMAP_VERSIONED_PATHS
            and parsed.query == "version=1"
        )
        if (
            parsed.scheme != "https"
            or parsed.hostname not in _ALLOWED_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or (parsed.query and not query_allowed)
            or parsed.fragment
            or port not in (None, 443)
            or not parsed.path.startswith("/")
        ):
            raise TransportError("invalid_response")
        try:
            if encoding == "json":
                payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                content_type = "application/json"
            elif encoding == "form":
                payload = urlencode(body).encode("utf-8")
                content_type = "application/x-www-form-urlencoded"
            else:
                raise TransportError("invalid_response")
        except (TypeError, ValueError, OverflowError):
            raise TransportError("invalid_response") from None

        request_headers = {
            key: value for key, value in headers.items() if key.lower() not in {"host", "content-length"}
        }
        request_headers["Accept"] = "application/json"
        request_headers["Content-Type"] = content_type
        connection: http.client.HTTPSConnection | None = None
        try:
            connection = http.client.HTTPSConnection(parsed.hostname, 443, timeout=timeout, context=_TLS_CONTEXT)
            connection.set_debuglevel(0)
            request_target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
            connection.request("POST", request_target, body=payload, headers=request_headers)
            response = connection.getresponse()
            retry_after = _retry_after(response.getheader("Retry-After"))
            if not 200 <= response.status < 300:
                return HttpReply(status=response.status, body={}, retry_after=retry_after)
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise TransportError("invalid_response")
            decoded = json.loads(raw)
            if not isinstance(decoded, dict):
                raise TransportError("invalid_response")
            return HttpReply(status=response.status, body=decoded, retry_after=retry_after)
        except TransportError:
            raise
        except TimeoutError:
            raise TransportError("timeout") from None
        except (OSError, http.client.HTTPException):
            raise TransportError("network") from None
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, OverflowError):
            raise TransportError("invalid_response") from None
        finally:
            if connection is not None:
                connection.close()
