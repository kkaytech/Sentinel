"""Request dependencies: database, authentication, CSRF and route permissions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, Request
from sqlalchemy import Engine

from sentinel.identity.sessions import AuthResult, authenticate, csrf_matches
from sentinel.shared.authz import Permission, Principal, require
from sentinel.shared.db import unit_of_work
from sentinel.shared.errors import SentinelError, unauthenticated
from sentinel.shared.settings import Settings

SESSION_COOKIE = "sentinel_session"
CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Marker for routes that need any authenticated user but no specific permission.
AUTHENTICATED = "AUTHENTICATED"
PUBLIC = "PUBLIC"


@dataclass(frozen=True)
class AuthContext:
    principal: Principal
    token_hmac: bytes
    csrf_token: str


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def utcnow() -> datetime:
    return datetime.now(UTC)


def current_auth(
    request: Request,
    engine: Engine = Depends(get_engine),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AuthContext:
    token = request.cookies.get(SESSION_COOKIE)
    # Commit session expiry/cleanup before raising, so the deletion is not rolled back.
    with unit_of_work(engine) as conn:
        outcome = authenticate(conn, settings, token, utcnow())
    if outcome.result is AuthResult.SESSION_EXPIRED:
        raise unauthenticated("SESSION_EXPIRED")
    if outcome.result is not AuthResult.OK:
        raise unauthenticated()
    assert outcome.principal and outcome.token_hmac and outcome.csrf_token
    if request.method in UNSAFE_METHODS and not csrf_matches(
        outcome.csrf_token, request.headers.get(CSRF_HEADER)
    ):
        raise SentinelError(403, "CSRF_INVALID", "Missing or invalid CSRF token.")
    return AuthContext(outcome.principal, outcome.token_hmac, outcome.csrf_token)


def _permission_dependency(permission: Permission | None) -> Callable[..., AuthContext]:
    def dependency(ctx: AuthContext = Depends(current_auth)) -> AuthContext:  # noqa: B008
        if permission is not None:
            require(ctx.principal, permission)
        return ctx

    return dependency


def protected(permission: Permission | None) -> dict[str, Any]:
    """Route keyword arguments: enforce the permission and record it in OpenAPI (FR-001.3).

    `None` means any authenticated user. The service layer repeats the check (NFR-006).
    """
    marker = permission.value if permission is not None else AUTHENTICATED
    return {
        "dependencies": [Depends(_permission_dependency(permission))],
        "openapi_extra": {"x-permission": marker},
    }


def public() -> dict[str, Any]:
    return {"openapi_extra": {"x-permission": PUBLIC}}
