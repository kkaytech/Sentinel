"""Table definitions for queries. The schema itself is owned by migrations (0006)."""

from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    CHAR,
    Boolean,
    Column,
    Date,
    DateTime,
    FetchedValue,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData(schema="app")

validation_runs = Table(
    "validation_runs",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("dataset_version_id", Uuid),
    Column("rule_set_version_id", Uuid),
    Column("engine_version", Text),
    Column("period", CHAR(7)),
    Column("reference_date", Date),
    Column("status", Text, server_default=FetchedValue()),
    Column("triggered_by", Uuid),
    Column("started_at", DateTime(timezone=True), server_default=FetchedValue()),
    Column("finished_at", DateTime(timezone=True)),
    Column("finding_counts", JSONB),
    Column("not_evaluated", JSONB),
    Column("error_detail", JSONB),
)

findings = Table(
    "findings",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("run_id", Uuid),
    Column("rule_id", Text),
    Column("rule_type", Text),
    Column("severity", Text),
    Column("waivable", Boolean),
    Column("table_name", Text),
    Column("columns", ARRAY(Text)),
    Column("failing_count", Integer),
    Column("evaluated_count", Integer),
    Column("truncated", Boolean),
    Column("samples", JSONB),
    Column("message", Text),
    Column("details", JSONB),
)

finding_records = Table(
    "finding_records",
    metadata,
    Column("finding_id", Uuid, primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("row_num", Integer),
    Column("record_key", Text),
    Column("group_no", Integer),
    Column("is_canonical", Boolean),
)
