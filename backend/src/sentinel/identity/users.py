"""User management (FR-001). Users are deactivated, never deleted."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, func, insert, select, update

from sentinel import audit
from sentinel.identity.passwords import MIN_PASSWORD_LENGTH, hash_password
from sentinel.identity.tables import user_roles, users
from sentinel.shared.authz import Permission, Principal, Role, require
from sentinel.shared.errors import not_found, validation_error

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


@dataclass(frozen=True)
class UserView:
    id: UUID
    username: str
    display_name: str
    is_active: bool
    roles: frozenset[Role]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "username": self.username,
            "display_name": self.display_name,
            "is_active": self.is_active,
            "roles": sorted(self.roles),
        }


def _validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise validation_error(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            {"field": "password"},
        )


def _validate_roles(roles: frozenset[Role]) -> None:
    if not roles:
        raise validation_error("At least one role is required.", {"field": "roles"})


def _active_roles(conn: Connection, user_id: UUID) -> frozenset[Role]:
    rows = conn.execute(
        select(user_roles.c.role).where(
            user_roles.c.user_id == user_id, user_roles.c.revoked_at.is_(None)
        )
    ).scalars()
    return frozenset(Role(r) for r in rows)


def get_user(conn: Connection, user_id: UUID) -> UserView | None:
    row = conn.execute(select(users).where(users.c.id == user_id)).mappings().one_or_none()
    if row is None:
        return None
    return UserView(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        is_active=row["is_active"],
        roles=_active_roles(conn, row["id"]),
    )


def load_principal(conn: Connection, user_id: UUID) -> Principal | None:
    """Return the principal for an active user, with roles as of now (FR-001.5)."""
    user = get_user(conn, user_id)
    if user is None or not user.is_active:
        return None
    return Principal(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        roles=user.roles,
    )


def _insert_user(
    conn: Connection,
    *,
    actor: Principal | None,
    username: str,
    display_name: str,
    password: str,
    roles: frozenset[Role],
) -> UserView:
    if not USERNAME_PATTERN.match(username):
        raise validation_error(
            "Username must be 3-64 characters: letters, digits, '.', '_' or '-'.",
            {"field": "username"},
        )
    if not 1 <= len(display_name) <= 200:
        raise validation_error("Display name must be 1-200 characters.", {"field": "display_name"})
    _validate_password(password)
    _validate_roles(roles)
    exists = conn.execute(
        select(users.c.id).where(func.lower(users.c.username) == username.lower())
    ).first()
    if exists is not None:
        raise validation_error("Username already exists.", {"field": "username"})

    user_id = conn.execute(
        insert(users)
        .values(username=username, display_name=display_name, password_hash=hash_password(password))
        .returning(users.c.id)
    ).scalar_one()
    granted_by = actor.user_id if actor else None
    for role in sorted(roles):
        conn.execute(insert(user_roles).values(user_id=user_id, role=role, granted_by=granted_by))
    audit.record(
        conn,
        actor=actor,
        event_type="USER_CREATED",
        entity_type="user",
        entity_id=str(user_id),
        payload={"username": username, "display_name": display_name, "roles": sorted(roles)},
    )
    view = get_user(conn, user_id)
    assert view is not None
    return view


def create_user(
    principal: Principal,
    conn: Connection,
    *,
    username: str,
    display_name: str,
    password: str,
    roles: frozenset[Role],
) -> UserView:
    require(principal, Permission.MANAGE_USERS)
    return _insert_user(
        conn,
        actor=principal,
        username=username,
        display_name=display_name,
        password=password,
        roles=roles,
    )


def create_user_as_system(
    conn: Connection,
    *,
    username: str,
    display_name: str,
    password: str,
    roles: frozenset[Role],
) -> UserView:
    """Bootstrap path used by the CLI (first administrator, demo seed). Audited as SYSTEM."""
    return _insert_user(
        conn,
        actor=None,
        username=username,
        display_name=display_name,
        password=password,
        roles=roles,
    )


def update_user(
    principal: Principal,
    conn: Connection,
    user_id: UUID,
    *,
    display_name: str | None = None,
    password: str | None = None,
    is_active: bool | None = None,
    roles: frozenset[Role] | None = None,
) -> UserView:
    require(principal, Permission.MANAGE_USERS)
    before = get_user(conn, user_id)
    if before is None:
        raise not_found("User")

    now = datetime.now(UTC)
    changes: dict[str, Any] = {}
    if display_name is not None and display_name != before.display_name:
        if not 1 <= len(display_name) <= 200:
            raise validation_error(
                "Display name must be 1-200 characters.", {"field": "display_name"}
            )
        changes["display_name"] = display_name
    if is_active is not None and is_active != before.is_active:
        changes["is_active"] = is_active
    if password is not None:
        _validate_password(password)
        changes["password_hash"] = hash_password(password)
    if changes:
        conn.execute(update(users).where(users.c.id == user_id).values(**changes, updated_at=now))

    if roles is not None:
        _validate_roles(roles)
        for role in before.roles - roles:
            conn.execute(
                update(user_roles)
                .where(
                    user_roles.c.user_id == user_id,
                    user_roles.c.role == role,
                    user_roles.c.revoked_at.is_(None),
                )
                .values(revoked_at=now, revoked_by=principal.user_id)
            )
        for role in sorted(roles - before.roles):
            conn.execute(
                insert(user_roles).values(user_id=user_id, role=role, granted_by=principal.user_id)
            )

    after = get_user(conn, user_id)
    assert after is not None
    if after != before or password is not None:
        diff_before: dict[str, Any] = {}
        diff_after: dict[str, Any] = {}
        for field in ("display_name", "is_active", "roles"):
            old, new = getattr(before, field), getattr(after, field)
            if old != new:
                diff_before[field] = sorted(old) if field == "roles" else old
                diff_after[field] = sorted(new) if field == "roles" else new
        audit.record(
            conn,
            actor=principal,
            event_type="USER_UPDATED",
            entity_type="user",
            entity_id=str(user_id),
            payload={
                "before": diff_before,
                "after": diff_after,
                "password_changed": password is not None,
            },
        )
    return after


def list_users(principal: Principal, conn: Connection) -> list[UserView]:
    require(principal, Permission.MANAGE_USERS)
    ids = conn.execute(select(users.c.id).order_by(func.lower(users.c.username))).scalars()
    result = []
    for user_id in ids:
        view = get_user(conn, user_id)
        if view is not None:
            result.append(view)
    return result
