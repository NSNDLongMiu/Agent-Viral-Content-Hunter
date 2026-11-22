"""Credential for the Claude leader only.

The dashboard API has no login: the server listens on loopback and `local_guard` keeps web pages from other
sites away. The review routes keep a separate service token so that nothing reachable from the dashboard (or from
a web page) can approve a brief; only the Claude leader can.
"""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from hunter.config import AuthSettings


class AuthService:
    def __init__(self, settings: AuthSettings) -> None:
        self.settings = settings

    def is_claude(self, token: str) -> bool:
        stored = self.settings.claude_service_token
        return bool(stored and secrets.compare_digest(token.encode(), stored.get_secret_value().encode()))


def auth_service(request: Request) -> AuthService:
    return request.app.state.auth


Auth = Annotated[AuthService, Depends(auth_service)]
_claude_bearer = HTTPBearer(scheme_name="ClaudeBearer", auto_error=False, description="Claude leader service token")


def unauthorized() -> HTTPException:
    return HTTPException(401, "Valid credentials required", headers={"WWW-Authenticate": "Bearer"})


def require_claude(
    auth: Auth,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_claude_bearer)],
) -> None:
    if credentials is None or not auth.is_claude(credentials.credentials):
        raise unauthorized()
