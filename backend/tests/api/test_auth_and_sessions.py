"""Authentication, sessions, CSRF and throttling (FR-001, NFR-002, ADR-009)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from sentinel.shared.authz import Role
from tests.conftest import TEST_PASSWORD, audit_events, login

pytestmark = pytest.mark.db


def test_health_is_public(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/v1/session"), ("GET", "/api/v1/users"), ("GET", "/api/v1/audit/events")],
)
def test_fr_001_1_protected_endpoints_require_session(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_login_sets_hardened_session_cookie(client: TestClient, make_user: Any) -> None:
    make_user("analyst_a", Role.ANALYST)
    response = client.post(
        "/api/v1/auth/login", json={"username": "analyst_a", "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["roles"] == ["ANALYST"] and body["csrf_token"]
    cookie = response.headers["set-cookie"].lower()
    assert "sentinel_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/v1/session").json()["user"]["username"] == "analyst_a"


def test_login_is_case_insensitive_on_username(client: TestClient, make_user: Any) -> None:
    make_user("MixedCase", Role.ANALYST)
    login(client, "mixedcase")


def test_failed_login_is_generic_for_unknown_and_wrong_password(
    client: TestClient, make_user: Any
) -> None:
    make_user("analyst_b", Role.ANALYST)
    wrong = client.post("/api/v1/auth/login", json={"username": "analyst_b", "password": "nope"})
    unknown = client.post("/api/v1/auth/login", json={"username": "ghost", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_nfr_002_2_eleventh_attempt_refused_even_with_correct_password(
    client: TestClient, make_user: Any
) -> None:
    make_user("analyst_c", Role.ANALYST)
    for _ in range(10):
        response = client.post(
            "/api/v1/auth/login", json={"username": "analyst_c", "password": "wrong-password"}
        )
        assert response.status_code == 401
    response = client.post(
        "/api/v1/auth/login", json={"username": "analyst_c", "password": TEST_PASSWORD}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_LOCKED"


def test_fr_001_4_deactivated_user_cannot_sign_in_but_stays_in_audit(
    client: TestClient, make_user: Any, owner_engine: Engine
) -> None:
    make_user("admin_d", Role.ADMIN)
    target = make_user("analyst_d", Role.ANALYST)
    csrf = login(client, "admin_d")
    response = client.patch(
        f"/api/v1/users/{target.id}", json={"is_active": False}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 200 and response.json()["is_active"] is False

    other = TestClient(client.app)
    response = other.post(
        "/api/v1/auth/login", json={"username": "analyst_d", "password": TEST_PASSWORD}
    )
    assert response.status_code == 401
    created = [e for e in audit_events(owner_engine) if e["event_type"] == "USER_CREATED"]
    assert str(target.id) in {e["entity_id"] for e in created}


def test_deactivation_ends_existing_sessions(client: TestClient, make_user: Any) -> None:
    make_user("admin_e", Role.ADMIN)
    target = make_user("analyst_e", Role.ANALYST)
    target_client = TestClient(client.app)
    login(target_client, "analyst_e")
    csrf = login(client, "admin_e")
    client.patch(
        f"/api/v1/users/{target.id}", json={"is_active": False}, headers={"X-CSRF-Token": csrf}
    )
    assert target_client.get("/api/v1/session").status_code == 401


def test_nfr_002_4_idle_session_expires(
    client: TestClient, make_user: Any, owner_engine: Engine
) -> None:
    make_user("analyst_f", Role.ANALYST)
    login(client, "analyst_f")
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE app.sessions SET last_seen_at = now() - interval '9 hours'"))
    response = client.get("/api/v1/session")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"
    with owner_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM app.sessions")).scalar_one() == 0


def test_nfr_002_3_state_change_without_csrf_token_is_rejected(
    client: TestClient, make_user: Any
) -> None:
    make_user("admin_g", Role.ADMIN)
    login(client, "admin_g")
    body = {
        "username": "new_user",
        "display_name": "New",
        "password": "long-enough-password",
        "roles": ["ANALYST"],
    }
    for headers in ({}, {"X-CSRF-Token": "forged"}):
        response = client.post("/api/v1/users", json=body, headers=headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CSRF_INVALID"


def test_logout_invalidates_session(client: TestClient, make_user: Any) -> None:
    make_user("analyst_h", Role.ANALYST)
    csrf = login(client, "analyst_h")
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/api/v1/session").status_code == 401


def test_session_tokens_are_stored_only_as_hmac(
    client: TestClient, make_user: Any, owner_engine: Engine
) -> None:
    make_user("analyst_i", Role.ANALYST)
    login(client, "analyst_i")
    cookie = client.cookies.get("sentinel_session")
    assert cookie
    with owner_engine.connect() as conn:
        stored = conn.execute(text("SELECT token_hmac FROM app.sessions")).scalar_one()
    assert cookie.encode() not in bytes(stored) and len(bytes(stored)) == 32


def test_nfr_002_1_no_plaintext_password_in_database_or_logs(
    client: TestClient, make_user: Any, owner_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    make_user("analyst_j", Role.ANALYST)
    login(client, "analyst_j")
    client.post("/api/v1/auth/login", json={"username": "analyst_j", "password": "bad-secret-x"})
    with owner_engine.connect() as conn:
        dump = conn.execute(
            text(
                "SELECT string_agg(t::text, ' ') FROM ("
                "SELECT row_to_json(u) AS t FROM app.users u UNION ALL "
                "SELECT row_to_json(e) FROM audit.events e) x"
            )
        ).scalar_one()
    assert TEST_PASSWORD not in dump and "bad-secret-x" not in dump
    assert TEST_PASSWORD not in caplog.text and "bad-secret-x" not in caplog.text


def test_validation_errors_never_echo_submitted_values(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login", json={"username": "", "password": "super-secret-value"}
    )
    assert response.status_code == 422
    assert "super-secret-value" not in response.text


def test_security_headers_present(client: TestClient) -> None:
    headers = client.get("/health").headers
    assert headers["content-security-policy"].startswith("default-src 'self'")
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-request-id"]
