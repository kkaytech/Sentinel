"""Login, server-side sessions, CSRF tokens and login throttling (ADR-009, NFR-002).

Functions return outcomes instead of raising for "failed" cases, so the caller can commit the
attempt record and audit event before returning an error response.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import Connection, delete, func, insert, select, update

from sentinel import audit
from sentinel.identity.passwords import dummy_hash, hash_password, needs_rehash, verify_password
from sentinel.identity.tables import login_attempts, sessions, users
from sentinel.identity.users import load_principal
from sentinel.shared.authz import Principal
from sentinel.shared.settings import Settings

ATTEMPT_RETENTION = timedelta(days=1)


class LoginResult(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    BAD_CREDENTIALS = "BAD_CREDENTIALS"
    LOCKED = "LOCKED"


@dataclass(frozen=True)
class LoginOutcome:
    result: LoginResult
    principal: Principal | None = None
    session_token: str | None = None
    csrf_token: str | None = None


class AuthResult(StrEnum):
    OK = "OK"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    SESSION_EXPIRED = "SESSION_EXPIRED"


@dataclass(frozen=True)
class AuthOutcome:
    result: AuthResult
    principal: Principal | None = None
    token_hmac: bytes | None = None
    csrf_token: str | None = None


def token_hmac(settings: Settings, token: str) -> bytes:
    """Sessions are stored by HMAC of the token, never the token itself."""
    return hmac.new(
        settings.session_secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256
    ).digest()


def login(
    conn: Connection, settings: Settings, username: str, password: str, now: datetime
) -> LoginOutcome:
    username_lower = username.strip().lower()
    window_start = now - timedelta(seconds=settings.login_window_seconds)
    conn.execute(
        delete(login_attempts).where(login_attempts.c.attempted_at < now - ATTEMPT_RETENTION)
    )
    recent_failures = conn.execute(
        select(func.count()).where(
            login_attempts.c.username_lower == username_lower,
            login_attempts.c.succeeded.is_(False),
            login_attempts.c.attempted_at >= window_start,
        )
    ).scalar_one()

    row = conn.execute(
        select(users.c.id, users.c.password_hash, users.c.is_active).where(
            func.lower(users.c.username) == username_lower
        )
    ).one_or_none()

    if recent_failures >= settings.login_failure_limit:
        _record_failure(conn, username_lower, row.id if row else None, "LOCKED", now)
        return LoginOutcome(LoginResult.LOCKED)

    password_ok = verify_password(row.password_hash if row else dummy_hash(), password)
    if row is None or not password_ok or not row.is_active:
        reason = "INACTIVE" if (row is not None and password_ok) else "BAD_CREDENTIALS"
        _record_failure(conn, username_lower, row.id if row else None, reason, now)
        return LoginOutcome(LoginResult.BAD_CREDENTIALS)

    if needs_rehash(row.password_hash):
        conn.execute(
            update(users)
            .where(users.c.id == row.id)
            .values(password_hash=hash_password(password), updated_at=now)
        )
    principal = load_principal(conn, row.id)
    if principal is None:  # pragma: no cover - guarded by is_active above
        return LoginOutcome(LoginResult.BAD_CREDENTIALS)

    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    conn.execute(
        insert(sessions).values(
            token_hmac=token_hmac(settings, session_token),
            user_id=row.id,
            csrf_token=csrf_token,
            created_at=now,
            last_seen_at=now,
        )
    )
    conn.execute(
        insert(login_attempts).values(
            username_lower=username_lower, attempted_at=now, succeeded=True
        )
    )
    audit.record(
        conn,
        actor=principal,
        event_type="LOGIN_SUCCEEDED",
        entity_type="user",
        entity_id=str(row.id),
        payload={"username": username_lower},
    )
    return LoginOutcome(LoginResult.SUCCEEDED, principal, session_token, csrf_token)


def _record_failure(
    conn: Connection, username_lower: str, user_id: object, reason: str, now: datetime
) -> None:
    conn.execute(
        insert(login_attempts).values(
            username_lower=username_lower, attempted_at=now, succeeded=False
        )
    )
    audit.record(
        conn,
        actor=None,
        event_type="LOGIN_FAILED",
        entity_type="user",
        entity_id=str(user_id) if user_id is not None else "-",
        payload={"username": username_lower, "reason": reason},
    )


def authenticate(
    conn: Connection, settings: Settings, session_token: str | None, now: datetime
) -> AuthOutcome:
    if not session_token:
        return AuthOutcome(AuthResult.UNAUTHENTICATED)
    key = token_hmac(settings, session_token)
    row = conn.execute(select(sessions).where(sessions.c.token_hmac == key)).mappings().first()
    if row is None:
        return AuthOutcome(AuthResult.UNAUTHENTICATED)
    if now - row["last_seen_at"] > timedelta(seconds=settings.session_idle_seconds):
        conn.execute(delete(sessions).where(sessions.c.token_hmac == key))
        return AuthOutcome(AuthResult.SESSION_EXPIRED)
    principal = load_principal(conn, row["user_id"])
    if principal is None:  # deactivated (FR-001.4)
        conn.execute(delete(sessions).where(sessions.c.token_hmac == key))
        return AuthOutcome(AuthResult.UNAUTHENTICATED)
    conn.execute(update(sessions).where(sessions.c.token_hmac == key).values(last_seen_at=now))
    return AuthOutcome(AuthResult.OK, principal, key, row["csrf_token"])


def logout(conn: Connection, principal: Principal, key: bytes) -> None:
    conn.execute(delete(sessions).where(sessions.c.token_hmac == key))
    audit.record(
        conn,
        actor=principal,
        event_type="LOGOUT",
        entity_type="user",
        entity_id=str(principal.user_id),
    )


def csrf_matches(expected: str | None, provided: str | None) -> bool:
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8"))
