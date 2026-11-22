"""Keep the login-free API reachable only from this machine's own pages.

Without a login, any web page open in the owner's browser could call http://127.0.0.1:8000: a form POST needs no
preflight (CSRF), and DNS rebinding makes a hostile site look same-origin. Two checks close both gaps:
- the Host header must name this machine (rebinding sends the attacker's host name; a server wrongly bound to a
  LAN address is refused for the same reason);
- a state-changing request that carries an Origin header must come from a local origin.
Callers that are not browsers (the leader CLI, curl, scripts) send no Origin and are unaffected.
"""

from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import Request, Response
from fastapi.responses import JSONResponse

# "testserver" is the host name Starlette's TestClient uses; a browser cannot be made to send it.
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "testserver"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _hostname(netloc: str) -> str | None:
    try:
        return urlsplit(f"//{netloc}").hostname
    except ValueError:
        return None


def _refusal() -> Response:
    return JSONResponse({"detail": "This API only answers local requests"}, status_code=403)


async def local_guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    if _hostname(request.headers.get("host", "")) not in LOCAL_HOSTS:
        return _refusal()
    origin = request.headers.get("origin")
    if origin is not None and request.method not in _SAFE_METHODS:
        try:
            origin_host = urlsplit(origin).hostname  # "null" (sandboxed frames) has no host and is refused
        except ValueError:
            origin_host = None
        if origin_host not in LOCAL_HOSTS:
            return _refusal()
    return await call_next(request)
