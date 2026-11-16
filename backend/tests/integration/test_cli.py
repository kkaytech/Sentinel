"""Bootstrap CLI: creating the first administrator."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text

from sentinel.identity.cli import main
from tests.conftest import audit_events

pytestmark = pytest.mark.db


@pytest.fixture
def cli_env(database: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_APP_DATABASE_URL", database["app"])
    monkeypatch.setenv("SENTINEL_SESSION_SECRET", "x" * 40)
    monkeypatch.setenv("SENTINEL_ENV", "test")


def test_create_user_audited_as_system(
    cli_env: None, owner_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SENTINEL_NEW_USER_PASSWORD", "a-long-admin-password")
    code = main(
        ["create-user", "--username", "admin", "--display-name", "Admin", "--role", "ADMIN"]
    )
    assert code == 0
    with owner_engine.connect() as conn:
        role = conn.execute(text("SELECT role FROM app.user_roles")).scalar_one()
    assert role == "ADMIN"
    (event,) = audit_events(owner_engine)
    assert event["event_type"] == "USER_CREATED" and event["actor_kind"] == "SYSTEM"


def test_rejects_short_password(
    cli_env: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SENTINEL_NEW_USER_PASSWORD", "short")
    code = main(["create-user", "--username", "admin", "--display-name", "A", "--role", "ADMIN"])
    assert code == 1 and "at least 12" in capsys.readouterr().err


def test_refuses_without_settings(
    database: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("SENTINEL_APP_DATABASE_URL", "SENTINEL_SESSION_SECRET", "SENTINEL_ENV"):
        monkeypatch.delenv(name, raising=False)
    assert main(["create-user", "--username", "a", "--display-name", "A", "--role", "ADMIN"]) == 2
