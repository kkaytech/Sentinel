"""Unit tests: role/permission policy (PRD §11.2), settings (NFR-003), passwords (NFR-002)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from sentinel.identity.passwords import hash_password, verify_password
from sentinel.shared.authz import (
    ROLE_PERMISSIONS,
    Permission,
    Principal,
    Role,
    permissions_for,
    require,
)
from sentinel.shared.errors import SentinelError
from sentinel.shared.settings import Settings, SettingsError

# PRD §11.2, written out independently of the implementation's map.
EXPECTED = {
    Permission.READ: {Role.ANALYST, Role.APPROVER, Role.ADMIN},
    Permission.DOWNLOAD_RAW: {Role.ANALYST, Role.APPROVER},
    Permission.INGEST: {Role.ANALYST},
    Permission.RUN_VALIDATION: {Role.ANALYST},
    Permission.REQUEST_EXPLANATION: {Role.ANALYST, Role.APPROVER},
    Permission.ADD_NOTE: {Role.ANALYST, Role.APPROVER},
    Permission.REQUEST_WAIVER: {Role.ANALYST},
    Permission.DECIDE_WAIVER: {Role.APPROVER},
    Permission.SUBMIT_REVIEW: {Role.ANALYST},
    Permission.DECIDE_REVIEW: {Role.APPROVER},
    Permission.DRY_RUN_PUBLICATION: {Role.ANALYST, Role.APPROVER, Role.ADMIN},
    Permission.PUBLISH: {Role.ANALYST, Role.APPROVER},
    Permission.EXPORT_PUBLICATION: {Role.ANALYST, Role.APPROVER, Role.ADMIN},
    Permission.MANAGE_USERS: {Role.ADMIN},
    Permission.RELOAD_CONFIG: {Role.ADMIN},
}


def principal(*roles: Role) -> Principal:
    return Principal(uuid4(), "u", "U", frozenset(roles))


@pytest.mark.parametrize("permission", list(Permission))
@pytest.mark.parametrize("role", list(Role))
def test_role_permission_matrix_matches_prd_11_2(role: Role, permission: Permission) -> None:
    assert (permission in ROLE_PERMISSIONS[role]) == (role in EXPECTED[permission])


def test_every_permission_is_specified() -> None:
    assert set(EXPECTED) == set(Permission)


def test_br_005_admin_alone_cannot_decide_or_publish() -> None:
    admin = principal(Role.ADMIN)
    for permission in (Permission.PUBLISH, Permission.DECIDE_REVIEW, Permission.DECIDE_WAIVER):
        with pytest.raises(SentinelError) as exc:
            require(admin, permission)
        assert exc.value.status == 403 and exc.value.code == "PERMISSION_DENIED"


def test_permissions_combine_across_roles() -> None:
    both = permissions_for(frozenset({Role.ANALYST, Role.APPROVER}))
    assert {Permission.SUBMIT_REVIEW, Permission.DECIDE_REVIEW} <= both


def test_require_rejects_missing_principal() -> None:
    with pytest.raises(SentinelError):
        require(None, Permission.READ)


def test_nfr_002_1_argon2id_hash_and_verify() -> None:
    hashed = hash_password("a-long-enough-password")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "a-long-enough-password")
    assert not verify_password(hashed, "wrong-password-here")
    assert not verify_password("not-a-hash", "anything")


def test_nfr_003_2_missing_session_secret_refuses_to_start() -> None:
    with pytest.raises(SettingsError, match="SENTINEL_SESSION_SECRET"):
        Settings.from_env({"SENTINEL_APP_DATABASE_URL": "postgresql://x", "SENTINEL_ENV": "test"})


def test_settings_reject_short_secret_and_unknown_env() -> None:
    base = {"SENTINEL_APP_DATABASE_URL": "postgresql://x", "SENTINEL_ENV": "test"}
    with pytest.raises(SettingsError, match="at least"):
        Settings.from_env({**base, "SENTINEL_SESSION_SECRET": "short"})
    with pytest.raises(SettingsError, match="SENTINEL_ENV"):
        Settings.from_env({**base, "SENTINEL_SESSION_SECRET": "x" * 40, "SENTINEL_ENV": "staging"})


def test_settings_from_env_ok() -> None:
    settings = Settings.from_env(
        {
            "SENTINEL_APP_DATABASE_URL": "postgresql://x",
            "SENTINEL_ENV": "demo",
            "SENTINEL_SESSION_SECRET": "x" * 40,
            "SENTINEL_HTTPS": "true",
        }
    )
    assert settings.https and settings.env == "demo"
