"""Table definitions for queries. The schema itself is owned by migrations (0002)."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    FetchedValue,
    LargeBinary,
    MetaData,
    Table,
    Text,
    Uuid,
)

metadata = MetaData(schema="app")

users = Table(
    "users",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("username", Text),
    Column("display_name", Text),
    Column("password_hash", Text),
    Column("is_active", Boolean),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

user_roles = Table(
    "user_roles",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("user_id", Uuid),
    Column("role", Text),
    Column("granted_by", Uuid),
    Column("granted_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
    Column("revoked_by", Uuid),
)

sessions = Table(
    "sessions",
    metadata,
    Column("token_hmac", LargeBinary, primary_key=True),
    Column("user_id", Uuid),
    Column("csrf_token", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("last_seen_at", DateTime(timezone=True)),
)

login_attempts = Table(
    "login_attempts",
    metadata,
    Column("id", BigInteger, primary_key=True, server_default=FetchedValue()),
    Column("username_lower", Text),
    Column("attempted_at", DateTime(timezone=True)),
    Column("succeeded", Boolean),
)
