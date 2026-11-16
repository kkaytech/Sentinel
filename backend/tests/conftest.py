"""Test fixtures.

Database tests need a PostgreSQL server reachable as a superuser via SENTINEL_TEST_ADMIN_URL
(default: the local throwaway cluster on port 55432). The suite creates the three Sentinel roles
if missing, creates a fresh `sentinel_test` database owned by sentinel_owner, runs the Alembic
migrations as the owner, and then connects as sentinel_app — exactly as production does.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url, text

from sentinel.api.app import create_app
from sentinel.identity.users import create_user_as_system
from sentinel.shared.authz import Role
from sentinel.shared.db import unit_of_work
from sentinel.shared.settings import Settings

BACKEND = Path(__file__).resolve().parents[1]
ROLES_SQL = BACKEND.parent / "db" / "init" / "create_roles.sql"
ADMIN_URL = os.environ.get(
    "SENTINEL_TEST_ADMIN_URL", "postgresql+psycopg://sentinel_admin@localhost:55432/postgres"
)
TEST_DB = "sentinel_test"
PASSWORDS = {
    "owner_password": "test-owner-password",
    "app_password": "test-app-password",
    "reader_password": "test-reader-password",
}
TEST_PASSWORD = "correct-horse-battery-staple"  # pragma: allowlist secret - test fixture only

RESET_TABLES = [
    "audit.events",
    "app.kpi_values",
    "app.run_impact_totals",
    "app.impact_figures",
    "app.finding_records",
    "app.findings",
    "app.validation_runs",
    "data.version_rows",
    "data.raw_files",
    "app.column_profiles",
    "app.ingestion_attempts",
    "app.dataset_versions",
    "app.dataset_periods",
    "app.active_config",
    "app.config_versions",
    "app.sessions",
    "app.login_attempts",
    "app.user_roles",
    "app.users",
]


def _url_for(user: str, password: str, database: str) -> str:
    url = make_url(ADMIN_URL).set(username=user, password=password, database=database)
    return url.render_as_string(hide_password=False)


def _roles_statements() -> list[str]:
    sql = "\n".join(
        line for line in ROLES_SQL.read_text().splitlines() if not line.startswith("--")
    )
    for name, value in PASSWORDS.items():
        sql = sql.replace(f":'{name}'", "'" + value.replace("'", "''") + "'")
    assert not re.search(r":'\w+'", sql), "unsubstituted psql variable"
    return [s.strip() for s in sql.split(";") if s.strip()]


@pytest.fixture(scope="session")
def database() -> Iterator[dict[str, str]]:
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment problem
        pytest.exit(f"PostgreSQL not reachable at {ADMIN_URL}: {exc}", returncode=3)
    with admin.connect() as conn:
        existing = set(
            conn.execute(text("SELECT rolname FROM pg_roles WHERE rolname LIKE 'sentinel_%'"))
            .scalars()
            .all()
        )
        for statement in _roles_statements():
            role = statement.split()[2]
            if role in existing:
                password_key = role.removeprefix("sentinel_") + "_password"
                conn.execute(text(f"ALTER ROLE {role} PASSWORD '{PASSWORDS[password_key]}'"))
            else:
                conn.execute(text(statement))
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        conn.execute(
            text(
                f"CREATE DATABASE {TEST_DB} OWNER sentinel_owner ENCODING 'UTF8' TEMPLATE template0"
            )
        )
    admin.dispose()

    urls = {
        "owner": _url_for("sentinel_owner", PASSWORDS["owner_password"], TEST_DB),
        "app": _url_for("sentinel_app", PASSWORDS["app_password"], TEST_DB),
        "reader": _url_for("sentinel_reader", PASSWORDS["reader_password"], TEST_DB),
        "admin": make_url(ADMIN_URL).set(database=TEST_DB).render_as_string(hide_password=False),
    }
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["url"] = urls["owner"]
    command.upgrade(cfg, "head")
    yield urls


@pytest.fixture(scope="session")
def owner_engine(database: dict[str, str]) -> Iterator[Engine]:
    engine = create_engine(database["owner"])
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(database: dict[str, str]) -> Iterator[Engine]:
    engine = create_engine(database["app"], pool_size=5, max_overflow=5)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_database(request: pytest.FixtureRequest) -> Iterator[None]:
    engine: Engine | None = (
        request.getfixturevalue("owner_engine") if "database" in request.fixturenames else None
    )
    yield
    if engine is None:
        return
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(RESET_TABLES)} RESTART IDENTITY CASCADE"))


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """A private copy of the shipped configuration, so a test can edit it and reload."""
    target = tmp_path / "config"
    shutil.copytree(BACKEND.parent / "config", target)
    return target


@pytest.fixture
def settings(database: dict[str, str], config_dir: Path) -> Settings:
    return Settings(
        app_database_url=database["app"],
        session_secret="test-session-secret-0123456789abcdef",
        env="test",
        config_dir=str(config_dir),
    )


@pytest.fixture
def client(settings: Settings, app_engine: Engine) -> Iterator[TestClient]:
    app = create_app(settings, engine=app_engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_user(app_engine: Engine) -> Any:
    def _make(username: str, *roles: Role, password: str = TEST_PASSWORD) -> Any:
        with unit_of_work(app_engine) as conn:
            return create_user_as_system(
                conn,
                username=username,
                display_name=username.replace("_", " ").title(),
                password=password,
                roles=frozenset(roles),
            )

    return _make


def login(client: TestClient, username: str, password: str = TEST_PASSWORD) -> str:
    """Log in and return the CSRF token. The session cookie stays on the client."""
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    token: str = response.json()["csrf_token"]
    return token


def audit_events(owner_engine: Engine) -> list[dict[str, Any]]:
    with owner_engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM audit.events ORDER BY id")).mappings()
        return [dict(r) for r in rows]
