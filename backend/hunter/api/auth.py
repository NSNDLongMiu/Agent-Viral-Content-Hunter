"""Scrypt login, process-local admin sessions and separate Claude credentials."""

import getpass
import hashlib
import secrets
import threading
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, SecretStr

from hunter.config import AuthSettings
from hunter.models.common import Model

_SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1, "maxmem": 64 * 1024 * 1024, "dklen": 32}


def hash_password(password: str) -> str:
    if not password or len(password) > 1024:
        raise ValueError("Use a password of 1–1024 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


class AuthService:
    def __init__(self, settings: AuthSettings) -> None:
        self.settings = settings
        self._sessions: dict[bytes, float] = {}
        self._lock = threading.Lock()

    def login(self, password: str) -> str | None:
        stored = self.settings.admin_password_hash
        if stored is None:
            return None
        _, salt, digest = stored.get_secret_value().split("$")
        candidate = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), **_SCRYPT)
        if not secrets.compare_digest(candidate, bytes.fromhex(digest)):
            return None
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._sessions = {key: expires for key, expires in self._sessions.items() if expires > now}
            self._sessions[self._digest(token)] = now + self.settings.session_ttl_seconds
        return token

    @staticmethod
    def _digest(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8")).digest()

    def is_admin(self, token: str) -> bool:
        with self._lock:
            return self._sessions.get(self._digest(token), 0) > time.monotonic()

    def logout(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(self._digest(token), None)

    def is_claude(self, token: str) -> bool:
        stored = self.settings.claude_service_token
        return bool(stored and secrets.compare_digest(token.encode(), stored.get_secret_value().encode()))


class LoginInput(Model):
    password: SecretStr = Field(min_length=1, max_length=1024)


class LoginResponse(Model):
    access_token: str = Field(repr=False)
    token_type: str = "bearer"
    expires_in: int


def auth_service(request: Request) -> AuthService:
    return request.app.state.auth


Auth = Annotated[AuthService, Depends(auth_service)]
_admin_bearer = HTTPBearer(scheme_name="AdminBearer", auto_error=False, description="Admin login session")
_claude_bearer = HTTPBearer(scheme_name="ClaudeBearer", auto_error=False, description="Claude leader service token")


def unauthorized() -> HTTPException:
    return HTTPException(401, "Valid credentials required", headers={"WWW-Authenticate": "Bearer"})


def require_admin(
    auth: Auth,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_admin_bearer)],
) -> str:
    if credentials is None or not auth.is_admin(credentials.credentials):
        raise unauthorized()
    return credentials.credentials


def require_claude(
    auth: Auth,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_claude_bearer)],
) -> None:
    if credentials is None or not auth.is_claude(credentials.credentials):
        raise unauthorized()


router = APIRouter(prefix="/auth", tags=["auth"], responses={401: {"description": "Valid credentials required"}})


@router.post("/login")
def login(data: LoginInput, auth: Auth, response: Response) -> LoginResponse:
    """Exchange the admin password for an expiring bearer session."""
    token = auth.login(data.password.get_secret_value())
    if token is None:
        raise unauthorized()
    response.headers["Cache-Control"] = "no-store"
    return LoginResponse(access_token=token, expires_in=auth.settings.session_ttl_seconds)


@router.post("/logout", status_code=204)
def logout(auth: Auth, token: Annotated[str, Depends(require_admin)]) -> None:
    """Revoke the current admin bearer session."""
    auth.logout(token)


if __name__ == "__main__":
    print(hash_password(getpass.getpass("Admin password: ")))
