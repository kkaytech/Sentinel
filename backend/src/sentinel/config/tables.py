"""Table definitions for queries. The schema itself is owned by migrations (0004)."""

from __future__ import annotations

from sqlalchemy import CHAR, Column, DateTime, FetchedValue, MetaData, Table, Text, Uuid

metadata = MetaData(schema="app")

config_versions = Table(
    "config_versions",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("kind", Text),
    Column("dataset_key", Text),
    Column("content_sha256", CHAR(64)),
    Column("source_text", Text),
    Column("canonical_json", Text),
    Column("loaded_by", Uuid),
    Column("loaded_at", DateTime(timezone=True), server_default=FetchedValue()),
)

active_config = Table(
    "active_config",
    metadata,
    Column("dataset_key", Text, primary_key=True),
    Column("contract_version_id", Uuid),
    Column("rule_set_version_id", Uuid),
    Column("activated_at", DateTime(timezone=True), server_default=FetchedValue()),
)
