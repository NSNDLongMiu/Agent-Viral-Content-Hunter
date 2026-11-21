import socket
import ssl
from email.message import Message
from io import BytesIO
from urllib.request import HTTPSHandler, OpenerDirector, ProxyHandler, Request, build_opener
from urllib.response import addinfourl

import pytest

from hunter.connectors import http
from hunter.connectors.http import HttpConnectorError, HttpResponse, get_body, urllib_transport
from hunter.interfaces import ConnectorError

URL = "https://example.org/feed"


@pytest.fixture(autouse=True)
def disallow_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_io(*args: object, **kwargs: object) -> None:
        pytest.fail("Network access attempted")

    monkeypatch.setattr(socket, "create_connection", unexpected_io)
    monkeypatch.setattr(socket, "getaddrinfo", unexpected_io)


@pytest.mark.parametrize("status", [302, 403, 429, 503])
def test_backoff_is_exposed_and_response_details_are_excluded(status: int) -> None:
    calls = []

    def fake_transport(url: str, timeout: float) -> HttpResponse:
        calls.append((url, timeout))
        return HttpResponse(status, b"fixture-private-body", {
            "lOcAtIoN": "https://example.com/login?token=fixture-private-token",
            "rEtRy-AfTeR": "25",
        })

    with pytest.raises(HttpConnectorError) as failure:
        get_body(URL, 2.5, fake_transport)

    assert failure.value.status == status
    assert failure.value.retry_after_seconds == 25
    assert "fixture-private" not in str(failure.value)
    assert calls == [(URL, 2.5)]


def test_retry_after_http_date_and_invalid_header() -> None:
    with pytest.raises(HttpConnectorError) as failure:
        get_body(URL, 3, lambda *_: HttpResponse(403, headers={"Retry-After": "Sat, 21 Nov 2015 00:00:00 GMT"}))
    assert failure.value.retry_after_seconds == 0

    with pytest.raises(HttpConnectorError) as invalid:
        get_body(URL, 3, lambda *_: HttpResponse(429, headers={"Retry-After": "fixture-private-header"}))
    assert invalid.value.retry_after_seconds is None
    assert "fixture-private" not in str(invalid.value)


@pytest.mark.parametrize("target", ["/login", "https://example.com/captcha", "/canonical-feed"])
def test_urllib_transport_stops_redirects_and_sends_only_generic_headers(
    target: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[Request] = []

    class FakeHTTPSHandler(HTTPSHandler):
        def https_open(self, request: Request) -> addinfourl:
            requests.append(request)
            headers = Message()
            headers["Location"] = target
            headers["Retry-After"] = "15"
            response = addinfourl(BytesIO(), headers, request.full_url, 302)
            response.msg = "Found"
            return response

    def fake_build_opener(
        proxy: ProxyHandler, redirects: http._NoRedirects, https: HTTPSHandler,
    ) -> OpenerDirector:
        assert proxy.proxies == {}
        assert https._context.verify_mode == ssl.CERT_REQUIRED
        assert https._context.check_hostname
        return build_opener(proxy, redirects, FakeHTTPSHandler())

    monkeypatch.setattr(http, "build_opener", fake_build_opener)
    with pytest.raises(HttpConnectorError, match="HTTP 302 redirect") as failure:
        get_body(URL, 1.25, urllib_transport)

    assert failure.value.retry_after_seconds == 15
    assert len(requests) == 1
    request = requests[0]
    assert request.full_url == URL and request.timeout == 1.25
    assert dict(request.header_items()) == {"Host": "example.org", "User-agent": "ViralContentHunter/0.1"}


def test_size_is_bounded_and_transport_failures_are_sanitized() -> None:
    with pytest.raises(ConnectorError, match="exceeded the size limit"):
        get_body(URL, 1, lambda *_: HttpResponse(200, b"x" * (http.MAX_BODY_BYTES + 1)))

    def failing_transport(url: str, timeout: float) -> HttpResponse:
        raise TimeoutError("fixture-private-transport-diagnostic")

    with pytest.raises(ConnectorError, match=r"^HTTP exchange failed\.$"):
        get_body(URL, 1, failing_transport)


def test_html_gate_is_rejected_without_disclosing_its_body() -> None:
    with pytest.raises(ConnectorError, match=r"HTML page instead of data") as failure:
        get_body(URL, 1, lambda *_: HttpResponse(200, b"fixture-private-response", {"Content-Type": "text/html"}))
    assert "fixture-private" not in str(failure.value)


def test_rate_limit_exhaustion_is_reported_without_a_retry() -> None:
    with pytest.raises(HttpConnectorError, match="rate limit reached") as failure:
        get_body(URL, 2, lambda *_: HttpResponse(404, headers={"X-RateLimit-Remaining": "0"}))
    assert failure.value.rate_limit_reached
    assert not failure.value.not_found
