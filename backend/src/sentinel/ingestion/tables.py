"""Table definitions for queries. The schema itself is owned by migrations (0005)."""

from __future__ import annotations

from sqlalchemy import (
    CHAR,
    Column,
    DateTime,
    FetchedValue,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

app_metadata = MetaData(schema="app")
data_metadata = MetaData(schema="data")

dataset_periods = Table(
    "dataset_periods",
    app_metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("dataset_key", Text),
    Column("period", CHAR(7)),
    Column("created_at", DateTime(timezone=True), server_default=FetchedValue()),
    Column("last_activity_at", DateTime(timezone=True), server_default=FetchedValue()),
)

dataset_versions = Table(
    "dataset_versions",
    app_metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("dataset_period_id", Uuid),
    Column("seq", Integer),
    Column("label", Text),
    Column("contract_version_id", Uuid),
    Column("content_hash", CHAR(64)),
    Column("hash_algorithm", Text),
    Column("columns", JSONB),
    Column("row_counts", JSONB),
    Column("status", Text, server_default=FetchedValue()),
    Column("created_by", Uuid),
    Column("created_at", DateTime(timezone=True), server_default=FetchedValue()),
)

ingestion_attempts = Table(
    "ingestion_attempts",
    app_metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("dataset_period_id", Uuid),
    Column("status", Text),
    Column("initiated_by", Uuid),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True), server_default=FetchedValue()),
    Column("files", JSONB),
    Column("errors", JSONB),
    Column("dataset_version_id", Uuid),
)

raw_files = Table(
    "raw_files",
    data_metadata,
    Column("dataset_version_id", Uuid, primary_key=True),
    Column("table_name", Text, primary_key=True),
    Column("filename", Text),
    Column("sha256", CHAR(64)),
    Column("size_bytes", Integer),
    Column("bytes", LargeBinary),
)

version_rows = Table(
    "version_rows",
    data_metadata,
    Column("dataset_version_id", Uuid, primary_key=True),
    Column("table_name", Text, primary_key=True),
    Column("row_num", Integer, primary_key=True),
    Column("cells", JSONB),
)
