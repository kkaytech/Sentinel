"""Alembic environment. Migrations always run as sentinel_owner, never as the app role."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, text

OWNER_ROLE = "sentinel_owner"


def _url() -> str:
    url = context.config.attributes.get("url") or os.environ.get("SENTINEL_OWNER_DATABASE_URL")
    if not url:
        raise RuntimeError("SENTINEL_OWNER_DATABASE_URL is required to run migrations")
    return str(url)


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        role = connection.execute(text("SELECT current_user")).scalar_one()
        if role != OWNER_ROLE:
            raise RuntimeError(f"Migrations must run as {OWNER_ROLE}, not {role!r}")
        # End the implicit transaction opened by the check above; otherwise Alembic runs
        # inside it and everything is rolled back when the connection closes.
        connection.commit()
        context.configure(
            connection=connection,
            version_table_schema="public",
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported")
run_migrations_online()
