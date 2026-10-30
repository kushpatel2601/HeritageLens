from __future__ import annotations

import hmac

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError

_bearer = HTTPBearer(auto_error=False)


class UnauthorizedError(AppError):
    status_code = 401
    title = "Unauthorized"


def token_matches(expected: str, creds: HTTPAuthorizationCredentials | None) -> bool:
    return creds is not None and hmac.compare_digest(creds.credentials.encode(), expected.encode())


def require_worker(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    """GPU/CPU workers authenticate with a shared bearer token (rotate via HL_WORKER_TOKEN)."""
    if not token_matches(request.app.state.services.settings.worker_token, creds):
        raise UnauthorizedError("invalid worker token")


def require_ingest(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    """Writes are open in dev; set HL_INGEST_TOKEN to lock them down in production."""
    expected = request.app.state.services.settings.ingest_token
    if expected and not token_matches(expected, creds):
        raise UnauthorizedError("invalid ingest token")
