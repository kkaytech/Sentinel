"""Database engine, unit of work, and the startup privilege self-check (ARD §7.3.1)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, create_engine, text

SENTINEL_SCHEMAS = ("app", "data", "published", "audit")


class DatabaseRoleError(RuntimeError):
    """The application is connected with more privilege than it may have. Refuse to start."""


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


@contextmanager
def unit_of_work(engine: Engine) -> Iterator[Connection]:
    """One transaction per command. Commits once on success, rolls back on any exception.

    Audit events are written on the same connection, so a failed audit insert rolls back the
    whole command (FR-015.2).
    """
    with engine.begin() as conn:
        yield conn


def check_database_role(engine: Engine) -> None:
    """Fail closed if the runtime role is privileged or owns Sentinel objects (ADR-018)."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls "
                "FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
        problems = [
            flag
            for flag, value in (
                ("SUPERUSER", row.rolsuper),
                ("CREATEROLE", row.rolcreaterole),
                ("CREATEDB", row.rolcreatedb),
                ("BYPASSRLS", row.rolbypassrls),
            )
            if value
        ]
        owns_schema = conn.execute(
            text(
                "SELECT count(*) FROM pg_namespace "
                "WHERE nspname = ANY(:schemas) AND nspowner = "
                "(SELECT oid FROM pg_roles WHERE rolname = current_user)"
            ),
            {"schemas": list(SENTINEL_SCHEMAS)},
        ).scalar_one()
        owns_relations = conn.execute(
            text(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = ANY(:schemas) AND c.relowner = "
                "(SELECT oid FROM pg_roles WHERE rolname = current_user)"
            ),
            {"schemas": list(SENTINEL_SCHEMAS)},
        ).scalar_one()
        if owns_schema or owns_relations:
            problems.append("OWNS_SENTINEL_OBJECTS")
        if problems:
            raise DatabaseRoleError(
                f"Refusing to start: database role {row.rolname!r} has {', '.join(problems)}. "
                "The application must connect as sentinel_app."
            )
