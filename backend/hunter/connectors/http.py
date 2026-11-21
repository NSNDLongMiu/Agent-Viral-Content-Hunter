"""Bounded, anonymous HTTP for the connector endpoints."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from ssl import create_default_context
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener

from hunter.config import BudgetSettings
from hunter.interfaces import ConnectorError

USER_AGENT = "ViralContentHunter/0.1"
MAX_BODY_BYTES = 2 * 1024 * 1024
_BUDGET = BudgetSettings()


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)


type Transport = Callable[[str, float], HttpResponse]


class HttpConnectorError(ConnectorError):
    def __init__(
        self, message: str, *, status: int, retry_after_seconds: int | None, rate_limit_reached: bool,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after_seconds = retry_after_seconds
        self.rate_limit_reached = rate_limit_reached

    @property
    def not_found(self) -> bool:
        return self.status == 404 and self.retry_after_seconds is None and not self.rate_limit_reached


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str,
    ) -> None:
        return None


def urllib_transport(url: str, timeout_seconds: float) -> HttpResponse:
    opener = build_opener(ProxyHandler({}), _NoRedirects(), HTTPSHandler(context=create_default_context()))
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            body = response.read(MAX_BODY_BYTES + 1) if response.status == 200 else b""
            return HttpResponse(response.status, body, dict(response.headers.items()))
    except HTTPError as response:
        with response:
            return HttpResponse(response.code, headers=dict(response.headers.items()))


def _retry_after(value: str) -> int | None:
    value = value.strip()
    try:
        if value.isascii() and value.isdecimal():
            return int(value)
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is not None:
            delay = retry_at - datetime.now(UTC)
            return max(0, delay.days * 86400 + delay.seconds + bool(delay.microseconds))
    except (ValueError, OverflowError):
        pass
    return None


def get_body(url: str, timeout_seconds: float, transport: Transport) -> bytes:
    """Get one HTTPS response and expose a server-requested delay to the caller."""
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username is not None:
            raise ValueError
    except ValueError:
        raise ConnectorError("An anonymous HTTPS endpoint is required.") from None

    _BUDGET.require_allowed(incurs_cost=False)
    try:
        response = transport(url, timeout_seconds)
    except (HTTPException, OSError, ValueError):
        raise ConnectorError("HTTP exchange failed.") from None

    headers = {name.casefold(): value for name, value in response.headers.items()}
    retry_after = _retry_after(headers.get("retry-after", ""))
    rate_limit_reached = headers.get("x-ratelimit-remaining", "").strip() == "0"
    status = response.status
    if status != 200 or retry_after is not None or rate_limit_reached:
        message = f"HTTP {status} from public endpoint."
        if 300 <= status < 400:
            message = f"HTTP {status} redirect from public endpoint."
        if retry_after is not None:
            message += " Server requested backoff."
        if rate_limit_reached:
            message += " Server rate limit reached."
        raise HttpConnectorError(
            message, status=status, retry_after_seconds=retry_after, rate_limit_reached=rate_limit_reached,
        )
    if headers.get("content-type", "").lower().startswith("text/html"):
        raise ConnectorError("Public endpoint returned an HTML page instead of data.")
    if len(response.body) > MAX_BODY_BYTES:
        raise ConnectorError("HTTP response exceeded the size limit.")
    return response.body
