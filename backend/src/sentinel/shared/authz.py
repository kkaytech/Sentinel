"""Authorisation policy: roles, permissions and the role → permission map (PRD §11.2).

This is the single source of truth for both service-layer checks and route metadata (FR-001).
It lives in `shared` so that every module, including `audit`, can enforce it without importing
`identity` (ARD CR-06).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sentinel.shared.errors import permission_denied


class Role(StrEnum):
    ANALYST = "ANALYST"
    APPROVER = "APPROVER"
    ADMIN = "ADMIN"


class Permission(StrEnum):
    READ = "READ"
    DOWNLOAD_RAW = "DOWNLOAD_RAW"
    INGEST = "INGEST"
    RUN_VALIDATION = "RUN_VALIDATION"
    REQUEST_EXPLANATION = "REQUEST_EXPLANATION"
    ADD_NOTE = "ADD_NOTE"
    REQUEST_WAIVER = "REQUEST_WAIVER"
    DECIDE_WAIVER = "DECIDE_WAIVER"
    SUBMIT_REVIEW = "SUBMIT_REVIEW"
    DECIDE_REVIEW = "DECIDE_REVIEW"
    DRY_RUN_PUBLICATION = "DRY_RUN_PUBLICATION"
    PUBLISH = "PUBLISH"
    EXPORT_PUBLICATION = "EXPORT_PUBLICATION"
    MANAGE_USERS = "MANAGE_USERS"
    RELOAD_CONFIG = "RELOAD_CONFIG"


_P = Permission

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ANALYST: frozenset(
        {
            _P.READ,
            _P.DOWNLOAD_RAW,
            _P.INGEST,
            _P.RUN_VALIDATION,
            _P.REQUEST_EXPLANATION,
            _P.ADD_NOTE,
            _P.REQUEST_WAIVER,
            _P.SUBMIT_REVIEW,
            _P.DRY_RUN_PUBLICATION,
            _P.PUBLISH,
            _P.EXPORT_PUBLICATION,
        }
    ),
    Role.APPROVER: frozenset(
        {
            _P.READ,
            _P.DOWNLOAD_RAW,
            _P.REQUEST_EXPLANATION,
            _P.ADD_NOTE,
            _P.DECIDE_WAIVER,
            _P.DECIDE_REVIEW,
            _P.DRY_RUN_PUBLICATION,
            _P.PUBLISH,
            _P.EXPORT_PUBLICATION,
        }
    ),
    # ADMIN alone holds no workflow decision or publication rights (BR-005).
    Role.ADMIN: frozenset(
        {
            _P.READ,
            _P.DRY_RUN_PUBLICATION,
            _P.EXPORT_PUBLICATION,
            _P.MANAGE_USERS,
            _P.RELOAD_CONFIG,
        }
    ),
}


@dataclass(frozen=True)
class Principal:
    """An authenticated, active user and the roles held at the time of the request."""

    user_id: UUID
    username: str
    display_name: str
    roles: frozenset[Role]

    @property
    def permissions(self) -> frozenset[Permission]:
        return permissions_for(self.roles)

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions


def permissions_for(roles: frozenset[Role]) -> frozenset[Permission]:
    granted: set[Permission] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS[role]
    return frozenset(granted)


def require(principal: Principal | None, permission: Permission) -> Principal:
    """Service-layer check. Call it first in every command and query (FR-001, NFR-006)."""
    if principal is None or not principal.has(permission):
        raise permission_denied()
    return principal
