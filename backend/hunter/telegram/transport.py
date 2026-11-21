"""Bounded, credential-safe access to the Telegram Bot API."""

import json
import ssl
from typing import Protocol
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from hunter.config import BudgetSettings

_TIMEOUT = 8.0
_MAX_RESPONSE_BYTES = 1024 * 1024


class TelegramTransport(Protocol):
    def __call__(self, request: Request, *, timeout: float) -> tuple[int, bytes]: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str,
    ) -> None:
        return None


def _urllib_transport(request: Request, *, timeout: float) -> tuple[int, bytes]:
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    tls.load_default_certs()
    opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=tls))
    try:
        response = opener.open(request, timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        return response.code, response.read(_MAX_RESPONSE_BYTES + 1)


class BotAPI:
    def __init__(self, token: str, transport: TelegramTransport | None) -> None:
        self._token = token
        self._transport = _urllib_transport if transport is None else transport
        self._budget = BudgetSettings()

    def post(self, method: str, data: dict[str, object]) -> tuple[int, dict[str, object]]:
        self._budget.require_allowed(incurs_cost=False)
        try:
            request = Request(
                f"https://api.telegram.org/bot{self._token}/{method}",
                data=json.dumps(data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            status, raw = self._transport(request, timeout=_TIMEOUT)
            if len(raw) <= _MAX_RESPONSE_BYTES:
                body = json.loads(raw)
                if isinstance(body, dict):
                    return status, body
        except Exception:
            # The URL, transport errors and API response text may contain credentials.
            pass
        return 0, {}
