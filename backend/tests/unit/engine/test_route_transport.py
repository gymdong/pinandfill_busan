import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import patch

import pytest

from app.adapters.route.quota import CallBudget
from app.adapters.route.transport import HttpReply, SafeHTTPTransport, TransportError


class FakeResponse:
    def __init__(self, status=200, body=b'{"ok":true}', headers=None):
        self.status = status
        self.body = body
        self.headers = headers or {}

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, amount):
        return self.body[:amount]


class FakeConnection:
    instances = []
    response = FakeResponse()
    error = None

    def __init__(self, host, port, *, timeout):
        self.host, self.port, self.timeout = host, port, timeout
        self.closed = False
        self.debuglevel = None
        self.request_args = None
        type(self).instances.append(self)

    def set_debuglevel(self, level):
        self.debuglevel = level

    def request(self, method, path, *, body, headers):
        if self.error:
            raise self.error
        self.request_args = method, path, body, headers

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_connection():
    FakeConnection.instances = []
    FakeConnection.response = FakeResponse()
    FakeConnection.error = None


def post(encoding="json", url="https://apis.openapi.sk.com/tmap/routes"):
    with patch("app.adapters.route.transport.http.client.HTTPSConnection", FakeConnection):
        return SafeHTTPTransport().post(
            url,
            headers={"appKey": "secret-key"},
            body={"startX": 129.1234567, "startY": 35.7654321},
            encoding=encoding,
            timeout=2,
        )


@pytest.mark.parametrize(
    "encoding,content_type",
    [
        ("json", "application/json"),
        ("form", "application/x-www-form-urlencoded"),
    ],
)
def test_post_encodes_body_closes_and_disables_debug(encoding, content_type):
    reply = post(encoding)
    connection = FakeConnection.instances[0]
    assert reply == HttpReply(200, {"ok": True})
    assert (connection.host, connection.port, connection.timeout) == ("apis.openapi.sk.com", 443, 2)
    assert connection.closed and connection.debuglevel == 0
    method, path, payload, headers = connection.request_args
    assert (method, path, headers["Content-Type"]) == ("POST", "/tmap/routes", content_type)
    if encoding == "json":
        assert json.loads(payload) == {"startX": 129.1234567, "startY": 35.7654321}
    else:
        assert payload == b"startX=129.1234567&startY=35.7654321"


def test_secrets_and_coordinates_are_not_represented_or_logged(caplog, capsys):
    with caplog.at_level("DEBUG"):
        reply = post()
    captured = capsys.readouterr()
    combined = repr(reply) + caplog.text + captured.out + captured.err
    for secret in ("secret-key", "129.1234567", "35.7654321"):
        assert secret not in combined


@pytest.mark.parametrize(
    "url",
    [
        "http://apis.openapi.sk.com/tmap/routes",
        "https://evil.example/routes",
        "https://api.odsay.com/v1/api/maasRP?apiKey=secret",
        "https://user:secret@api.odsay.com/v1/api/maasRP",
        "https://api.odsay.com:444/v1/api/maasRP",
    ],
)
def test_invalid_or_secret_bearing_urls_are_rejected(url):
    with pytest.raises(TransportError) as error:
        SafeHTTPTransport().post(url, headers={}, body={}, encoding="form", timeout=1)
    assert error.value.kind == "invalid_response"
    assert "secret" not in repr(error.value)


@pytest.mark.parametrize("path", ["routes", "routes/pedestrian", "routes/prediction"])
def test_tmap_version_query_is_preserved_only_for_documented_paths(path):
    reply = post(url=f"https://apis.openapi.sk.com/tmap/{path}?version=1")
    assert reply.status == 200
    assert FakeConnection.instances[0].request_args[1] == f"/tmap/{path}?version=1"


@pytest.mark.parametrize(
    "url",
    [
        "https://apis.openapi.sk.com/tmap/routes?version=2",
        "https://apis.openapi.sk.com/tmap/routes?version=1&appKey=secret",
        "https://apis.openapi.sk.com/transit/routes?version=1",
        "https://api.odsay.com/v1/api/maasRP?version=1",
    ],
)
def test_other_query_parameters_are_rejected(url):
    with pytest.raises(TransportError, match="invalid_response"):
        post(url=url)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout_is_rejected(timeout):
    with pytest.raises(TransportError, match="invalid_response"):
        SafeHTTPTransport().post(
            "https://api.odsay.com/v1/api/maasRP", headers={}, body={}, encoding="form", timeout=timeout
        )


def test_network_timeout_is_sanitized_and_connection_closes():
    FakeConnection.error = TimeoutError("coordinate 129.1234567")
    with pytest.raises(TransportError) as error:
        post()
    assert error.value.kind == "timeout"
    assert "129.1234567" not in repr(error.value)
    assert FakeConnection.instances[0].closed


@pytest.mark.parametrize("body", [b"not-json", b"[]", b'"scalar"', b"{}"])
def test_invalid_json_shapes(body):
    FakeConnection.response = FakeResponse(body=body)
    if body == b"{}":
        assert post().body == {}
    else:
        with pytest.raises(TransportError, match="invalid_response"):
            post()
    assert FakeConnection.instances[0].closed


def test_oversized_response_is_rejected():
    FakeConnection.response = FakeResponse(body=b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(TransportError, match="invalid_response"):
        post()


@pytest.mark.parametrize("status", [301, 401, 429, 503])
def test_non_success_does_not_parse_or_expose_body(status):
    FakeConnection.response = FakeResponse(status=status, body=b'{"secret":"coordinate"}', headers={"Retry-After": "7"})
    reply = post()
    assert reply == HttpReply(status, {}, 7.0)
    assert "coordinate" not in repr(reply)


def test_http_date_retry_after_is_supported():
    future = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    FakeConnection.response = FakeResponse(status=429, headers={"Retry-After": future})
    reply = post()
    assert reply.retry_after is not None and 0 <= reply.retry_after <= 30


class ManualClock:
    value = 0.0

    def __call__(self):
        return self.value


def test_budget_rolling_window_boundary_and_pause():
    clock = ManualClock()
    budget = CallBudget(2, 10, clock=clock)
    assert budget.allow() and budget.allow() and not budget.allow()
    clock.value = 10
    assert budget.allow()
    budget.pause(5)
    assert not budget.allow()
    clock.value = 15
    assert budget.allow()


def test_budget_is_thread_safe():
    budget = CallBudget(17, 60, clock=lambda: 1.0)
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: budget.allow(), range(100)))
    assert sum(results) == 17


@pytest.mark.parametrize(
    "args",
    [(-1, 1), (True, 1), (1.5, 1), (1, 0), (1, float("inf")), (1, float("nan"))],
)
def test_budget_rejects_invalid_configuration(args):
    with pytest.raises(ValueError):
        CallBudget(*args)


@pytest.mark.parametrize("seconds", [-1, float("inf"), float("nan")])
def test_budget_rejects_invalid_pause(seconds):
    with pytest.raises(ValueError):
        CallBudget(1).pause(seconds)


def test_zero_limit_never_allows_calls():
    assert not CallBudget(0).allow()
