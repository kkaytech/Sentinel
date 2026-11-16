"""Authentication and session endpoints (Doc 4 §3.1)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from sentinel.api.deps import (
    SESSION_COOKIE,
    AuthContext,
    current_auth,
    get_engine,
    get_settings,
    protected,
    public,
    utcnow,
)
from sentinel.identity.sessions import LoginResult, login, logout
from sentinel.shared.authz import Principal
from sentinel.shared.db import unit_of_work
from sentinel.shared.errors import SentinelError, unauthenticated
from sentinel.shared.settings import Settings

router = APIRouter(prefix="/api/v1")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


def _principal_body(principal: Principal, csrf_token: str) -> dict[str, Any]:
    return {
        "user": {
            "id": str(principal.user_id),
            "username": principal.username,
            "display_name": principal.display_name,
        },
        "roles": sorted(principal.roles),
        "csrf_token": csrf_token,
    }


@router.post("/auth/login", **public())
def post_login(
    body: LoginRequest,
    response: Response,
    engine: Engine = Depends(get_engine),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict[str, Any]:
    # The attempt record and audit event must commit even when the login fails.
    with unit_of_work(engine) as conn:
        outcome = login(conn, settings, body.username, body.password, utcnow())
    if outcome.result is LoginResult.LOCKED:
        raise SentinelError(
            403, "ACCOUNT_LOCKED", "Too many failed sign-in attempts. Try again later."
        )
    if outcome.result is not LoginResult.SUCCEEDED:
        raise SentinelError(401, "UNAUTHENTICATED", "Invalid username or password.")
    assert outcome.principal and outcome.session_token and outcome.csrf_token
    response.set_cookie(
        SESSION_COOKIE,
        outcome.session_token,
        httponly=True,
        samesite="lax",
        secure=settings.https,
        path="/",
    )
    return _principal_body(outcome.principal, outcome.csrf_token)


@router.post("/auth/logout", status_code=204, **protected(None))
def post_logout(
    response: Response,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> Response:
    with unit_of_work(engine) as conn:
        logout(conn, ctx.principal, ctx.token_hmac)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/session", **protected(None))
def get_session(ctx: AuthContext = Depends(current_auth)) -> dict[str, Any]:  # noqa: B008
    if ctx.principal is None:  # pragma: no cover - current_auth guarantees a principal
        raise unauthenticated()
    return _principal_body(ctx.principal, ctx.csrf_token)
