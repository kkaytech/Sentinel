"""Database privilege model (ADR-018, ARD §7.3): grant drift, immutability, guards, self-check."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from psycopg import errors
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from sentinel.audit import record
from sentinel.shared.authz import Role
from sentinel.shared.db import DatabaseRoleError, check_database_role

pytestmark = pytest.mark.db
EXPECTED = json.loads((Path(__file__).parent / "expected_privileges.json").read_text())
SCHEMAS = ("app", "data", "published", "audit")


def _actual_privileges(owner_engine: Engine) -> dict[str, dict[str, object]]:
    actual: dict[str, dict[str, object]] = {"table": {}, "column_update": {}, "sequence_usage": {}}
    with owner_engine.connect() as conn:
        for role in ("sentinel_app", "sentinel_reader"):
            tables: dict[str, list[str]] = {}
            for schema, table, priv in conn.execute(
                text(
                    "SELECT table_schema, table_name, privilege_type "
                    "FROM information_schema.role_table_grants "
                    "WHERE grantee = :role AND table_schema = ANY(:schemas)"
                ),
                {"role": role, "schemas": list(SCHEMAS)},
            ):
                tables.setdefault(f"{schema}.{table}", []).append(priv)
            actual["table"][role] = {k: sorted(v) for k, v in tables.items()}

            columns: dict[str, list[str]] = {}
            for schema, table, column in conn.execute(
                text(
                    "SELECT table_schema, table_name, column_name "
                    "FROM information_schema.column_privileges "
                    "WHERE grantee = :role AND privilege_type = 'UPDATE' "
                    "AND table_schema = ANY(:schemas)"
                ),
                {"role": role, "schemas": list(SCHEMAS)},
            ):
                columns.setdefault(f"{schema}.{table}", []).append(column)
            actual["column_update"][role] = {k: sorted(v) for k, v in columns.items()}

            sequences = conn.execute(
                text(
                    "SELECT n.nspname || '.' || c.relname FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE c.relkind = 'S' AND n.nspname = ANY(:schemas) "
                    "AND CASE WHEN c.relkind = 'S' "
                    "THEN has_sequence_privilege(:role, c.oid, 'USAGE') ELSE false END "
                    "ORDER BY 1"
                ),
                {"role": role, "schemas": list(SCHEMAS)},
            ).scalars()
            actual["sequence_usage"][role] = list(sequences)
    return actual


def test_adr_018_grant_drift(owner_engine: Engine) -> None:
    actual = _actual_privileges(owner_engine)
    expected = {k: v for k, v in EXPECTED.items() if not k.startswith("_")}
    assert actual == expected


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit.events SET event_type = 'TAMPERED'",
        "DELETE FROM audit.events",
        "TRUNCATE audit.events",
        "UPDATE app.users SET username = 'renamed'",
        "DELETE FROM app.users",
        "UPDATE app.user_roles SET role = 'ADMIN'",
        "DELETE FROM app.user_roles",
        "UPDATE app.login_attempts SET succeeded = true",
        "SELECT setval('audit.events_id_seq', 1)",
        "ALTER TABLE audit.events DISABLE TRIGGER ALL",
        "DROP TRIGGER events_forbid_update ON audit.events",
        "CREATE TABLE app.rogue (id int)",
    ],
)
def test_fr_015_3_app_role_cannot_modify_history(
    app_engine: Engine, owner_engine: Engine, make_user: Any, statement: str
) -> None:
    make_user("someone", Role.ANALYST)
    with pytest.raises(DBAPIError) as exc, app_engine.begin() as conn:
        conn.execute(text(statement))
    assert isinstance(exc.value.orig, errors.InsufficientPrivilege), exc.value.orig


def test_column_limited_update_allowed_for_granted_columns(
    app_engine: Engine, make_user: Any
) -> None:
    user = make_user("columns_ok", Role.ANALYST)
    with app_engine.begin() as conn:
        conn.execute(
            text("UPDATE app.users SET display_name = 'Renamed' WHERE id = :id"), {"id": user.id}
        )


def test_owner_role_bypasses_triggers_for_maintenance(
    owner_engine: Engine, app_engine: Engine
) -> None:
    with app_engine.begin() as conn:
        record(conn, actor=None, event_type="TEST_EVENT", entity_type="test", entity_id="1")
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE audit.events SET payload = '{\"x\": 1}'::jsonb"))


@pytest.mark.parametrize(
    ("grant", "statement"),
    [
        ("GRANT UPDATE ON audit.events TO sentinel_app", "UPDATE audit.events SET entity_id = 'x'"),
        ("GRANT DELETE ON audit.events TO sentinel_app", "DELETE FROM audit.events"),
        ("GRANT TRUNCATE ON audit.events TO sentinel_app", "TRUNCATE audit.events"),
        ("GRANT UPDATE ON app.users TO sentinel_app", "UPDATE app.users SET username = 'renamed'"),
        ("GRANT DELETE ON app.users TO sentinel_app", "DELETE FROM app.users"),
        (
            "GRANT UPDATE ON app.user_roles TO sentinel_app",
            "UPDATE app.user_roles SET role = 'ADMIN'",
        ),
    ],
)
def test_triggers_block_changes_even_if_grants_drift(
    database: dict[str, str], app_engine: Engine, make_user: Any, grant: str, statement: str
) -> None:
    """Second, independent layer (ARD §7.3): triggers stop the change with grants removed."""
    make_user("victim", Role.ANALYST)
    with app_engine.begin() as conn:
        record(conn, actor=None, event_type="TEST_EVENT", entity_type="test", entity_id="1")
    admin = create_engine(database["admin"])
    try:
        with admin.connect() as conn:
            trans = conn.begin()
            conn.execute(text(grant))
            conn.execute(text("SET LOCAL ROLE sentinel_app"))
            with pytest.raises(DBAPIError, match="sentinel:"):
                conn.execute(text(statement))
            trans.rollback()  # also undoes the temporary grant
    finally:
        admin.dispose()


@pytest.fixture
def sealed_tables(owner_engine: Engine) -> Iterator[None]:
    """Throwaway parent/child tables using the real seal-guard trigger function."""
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE app.t_parent (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
                "creating_xact xid8 NOT NULL DEFAULT pg_current_xact_id())"
            )
        )
        conn.execute(
            text("CREATE TABLE app.t_child (parent_id uuid NOT NULL REFERENCES app.t_parent(id))")
        )
        conn.execute(
            text(
                "CREATE TRIGGER t_child_seal BEFORE INSERT ON app.t_child FOR EACH ROW "
                "EXECUTE FUNCTION app.sentinel_seal_guard('app.t_parent', 'parent_id')"
            )
        )
        conn.execute(text("GRANT SELECT, INSERT ON app.t_parent, app.t_child TO sentinel_app"))
    yield
    with owner_engine.begin() as conn:
        conn.execute(text("DROP TABLE app.t_child, app.t_parent"))


def test_seal_guard_allows_children_only_in_creating_transaction(
    sealed_tables: None, app_engine: Engine
) -> None:
    with app_engine.begin() as conn:
        parent_id = conn.execute(
            text("INSERT INTO app.t_parent DEFAULT VALUES RETURNING id")
        ).scalar_one()
        conn.execute(text("INSERT INTO app.t_child VALUES (:p)"), {"p": parent_id})
    with pytest.raises(DBAPIError, match="is sealed"), app_engine.begin() as conn:
        conn.execute(text("INSERT INTO app.t_child VALUES (:p)"), {"p": parent_id})


def test_startup_self_check_accepts_app_role(app_engine: Engine) -> None:
    check_database_role(app_engine)


def test_startup_self_check_rejects_owner_and_superuser(database: dict[str, str]) -> None:
    for key, reason in (("owner", "OWNS_SENTINEL_OBJECTS"), ("admin", "SUPERUSER")):
        engine = create_engine(database[key])
        try:
            with pytest.raises(DatabaseRoleError, match=reason):
                check_database_role(engine)
        finally:
            engine.dispose()


def test_reader_role_cannot_read_application_tables(database: dict[str, str]) -> None:
    engine = create_engine(database["reader"])
    try:
        with pytest.raises(ProgrammingError), engine.connect() as conn:
            conn.execute(text("SELECT * FROM app.users"))
    finally:
        engine.dispose()
