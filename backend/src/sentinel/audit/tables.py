"""Table definitions for queries. The schema itself is owned by migrations (0003)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, FetchedValue, MetaData, Table, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData(schema="audit")

events = Table(
    "events",
    metadata,
    Column("id", BigInteger, primary_key=True, server_default=FetchedValue()),
    Column("event_id", Uuid, server_default=FetchedValue()),
    Column("occurred_at", DateTime(timezone=True)),
    Column("actor_kind", Text),
    Column("actor_user_id", Uuid),
    Column("event_type", Text),
    Column("entity_type", Text),
    Column("entity_id", Text),
    Column("dataset_version_id", Uuid),
    Column("payload", JSONB),
    Column("correlation_id", Text),
)
