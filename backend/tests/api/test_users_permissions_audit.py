"""Route permissions (FR-001.2/.3), user administration (FR-001.5), audit coverage (FR-015)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from sentinel.api.app import create_app
from sentinel.api.audit_map import AUDITED_ROUTES
from sentinel.api.deps import AUTHENTICATED, PUBLIC
from sentinel.shared.authz import ROLE_PERMISSIONS, Permission, Role
from sentinel.shared.settings import Settings
from tests.conftest import audit_events, login

pytestmark = pytest.mark.db
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
EXPECTED_OPERATIONS = 40  # guards against these tests passing vacuously


def _operations(settings: Settings, app_engine: Engine) -> list[tuple[str, str, dict[str, Any]]]:
    """(METHOD, path, operation) from the generated OpenAPI document (FR-016.2)."""
    schema = create_app(settings, engine=app_engine).openapi()
    ops = [
        (method.upper(), path, operation)
        for path, item in schema["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    ]
    assert len(ops) >= EXPECTED_OPERATIONS, f"only {len(ops)} operations found"
    return ops


def test_fr_001_3_every_route_declares_a_permission(settings: Settings, app_engine: Engine) -> None:
    allowed = {p.value for p in Permission} | {AUTHENTICATED, PUBLIC}
    for method, path, operation in _operations(settings, app_engine):
        assert operation.get("x-permission") in allowed, f"{method} {path} has no permission"


def test_only_login_and_health_are_public(settings: Settings, app_engine: Engine) -> None:
    public = {
        path
        for _, path, operation in _operations(settings, app_engine)
        if operation.get("x-permission") == PUBLIC
    }
    assert public == {"/health", "/api/v1/auth/login"}


def test_nfr_007_4_every_state_changing_route_has_an_audit_mapping(
    settings: Settings, app_engine: Engine
) -> None:
    unsafe = {f"{m} {p}" for m, p, _ in _operations(settings, app_engine) if m in UNSAFE}
    assert unsafe, "no state-changing routes found"
    assert unsafe == set(AUDITED_ROUTES)


def test_fr_015_4_no_mutating_audit_routes(settings: Settings, app_engine: Engine) -> None:
    for method, path, _ in _operations(settings, app_engine):
        if path.startswith("/api/v1/audit"):
            assert method == "GET"


# FR-001.2: endpoint x role matrix, derived from the route's declared permission.
ENDPOINTS = [
    ("GET", "/api/v1/users", Permission.MANAGE_USERS),
    ("GET", "/api/v1/audit/events", Permission.READ),
    ("GET", "/api/v1/session", None),
    ("GET", "/api/v1/datasets/SUPINV/config", Permission.READ),
    ("GET", "/api/v1/datasets/SUPINV/periods", Permission.READ),
]


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize(("method", "path", "permission"), ENDPOINTS)
def test_fr_001_2_permission_matrix(
    client: TestClient,
    make_user: Any,
    role: Role,
    method: str,
    path: str,
    permission: Permission | None,
) -> None:
    make_user(f"user_{role.lower()}", role)
    login(client, f"user_{role.lower()}")
    response = client.request(method, path)
    allowed = permission is None or permission in ROLE_PERMISSIONS[role]
    assert response.status_code == (200 if allowed else 403), response.text


def test_create_user_requires_admin_and_validates_password(
    client: TestClient, make_user: Any
) -> None:
    make_user("analyst_k", Role.ANALYST)
    csrf = login(client, "analyst_k")
    body = {
        "username": "x_user",
        "display_name": "X",
        "password": "long-enough-pw",
        "roles": ["ANALYST"],
    }
    response = client.post("/api/v1/users", json=body, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 403

    admin_client = TestClient(client.app)
    make_user("admin_k", Role.ADMIN)
    csrf = login(admin_client, "admin_k")
    short = {**body, "password": "short"}
    response = admin_client.post("/api/v1/users", json=short, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
    response = admin_client.post("/api/v1/users", json=body, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 201
    duplicate = {**body, "username": "X_USER"}
    response = admin_client.post("/api/v1/users", json=duplicate, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 422


def test_fr_001_5_role_change_effective_next_request_and_audited(
    client: TestClient, make_user: Any, owner_engine: Engine
) -> None:
    make_user("admin_m", Role.ADMIN)
    target = make_user("analyst_m", Role.ANALYST)
    target_client = TestClient(client.app)
    login(target_client, "analyst_m")
    assert target_client.get("/api/v1/users").status_code == 403

    csrf = login(client, "admin_m")
    response = client.patch(
        f"/api/v1/users/{target.id}",
        json={"roles": ["ANALYST", "ADMIN"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200 and response.json()["roles"] == ["ADMIN", "ANALYST"]
    assert target_client.get("/api/v1/users").status_code == 200

    updated = [e for e in audit_events(owner_engine) if e["event_type"] == "USER_UPDATED"]
    assert len(updated) == 1
    assert updated[0]["payload"]["before"] == {"roles": ["ANALYST"]}
    assert updated[0]["payload"]["after"] == {"roles": ["ADMIN", "ANALYST"]}


def _event_types_after(owner_engine: Engine, start: int) -> list[str]:
    return [e["event_type"] for e in audit_events(owner_engine)[start:]]


def test_fr_015_1_each_state_change_writes_exactly_one_event(
    client: TestClient, make_user: Any, owner_engine: Engine
) -> None:
    make_user("admin_n", Role.ADMIN)
    start = len(audit_events(owner_engine))
    csrf = login(client, "admin_n")
    assert _event_types_after(owner_engine, start) == ["LOGIN_SUCCEEDED"]

    start = len(audit_events(owner_engine))
    response = client.post(
        "/api/v1/users",
        json={
            "username": "audited",
            "display_name": "A",
            "password": "long-enough-pw",
            "roles": ["APPROVER"],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert _event_types_after(owner_engine, start) == ["USER_CREATED"]

    start = len(audit_events(owner_engine))
    client.patch(
        f"/api/v1/users/{response.json()['id']}",
        json={"display_name": "Audited"},
        headers={"X-CSRF-Token": csrf},
    )
    assert _event_types_after(owner_engine, start) == ["USER_UPDATED"]

    start = len(audit_events(owner_engine))
    client.post("/api/v1/auth/login", json={"username": "admin_n", "password": "wrong-one"})
    assert _event_types_after(owner_engine, start) == ["LOGIN_FAILED"]

    start = len(audit_events(owner_engine))
    client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert _event_types_after(owner_engine, start) == ["LOGOUT"]


def test_fr_015_2_failed_audit_write_rolls_back_the_action(
    client: TestClient, make_user: Any, owner_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_user("admin_o", Role.ADMIN)
    csrf = login(client, "admin_o")

    def broken_record(*_: Any, **__: Any) -> None:
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr("sentinel.identity.users.audit.record", broken_record)
    no_raise = TestClient(client.app, raise_server_exceptions=False)
    no_raise.cookies = client.cookies
    response = no_raise.post(
        "/api/v1/users",
        json={
            "username": "rolled_back",
            "display_name": "R",
            "password": "long-enough-pw",
            "roles": ["ANALYST"],
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    monkeypatch.undo()
    listing = client.get("/api/v1/users").json()["items"]
    assert "rolled_back" not in {u["username"] for u in listing}


def test_fr_015_5_audit_viewer_filters_chronologically(client: TestClient, make_user: Any) -> None:
    admin = make_user("admin_p", Role.ADMIN)
    login(client, "admin_p")
    response = client.get(
        "/api/v1/audit/events", params={"entity_type": "user", "entity_id": str(admin.id)}
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert [e["event_type"] for e in items] == ["USER_CREATED", "LOGIN_SUCCEEDED"]
    assert [e["id"] for e in items] == sorted(e["id"] for e in items)
