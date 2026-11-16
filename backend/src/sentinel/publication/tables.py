"""Table definitions for queries. The schema itself is owned by migrations (0009)."""

from __future__ import annotations

from sqlalchemy import (
    CHAR,
    Column,
    Date,
    DateTime,
    FetchedValue,
    LargeBinary,
    MetaData,
    Numeric,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

app_metadata = MetaData(schema="app")
published_metadata = MetaData(schema="published")

publications = Table(
    "publications",
    app_metadata,
    Column("id", Uuid, primary_key=True),
    Column("publication_ref", Text),
    Column("dataset_period_id", Uuid),
    Column("dataset_key", Text),
    Column("period", CHAR(7)),
    Column("dataset_version_id", Uuid),
    Column("content_hash", CHAR(64)),
    Column("validation_run_id", Uuid),
    Column("rule_set_version_id", Uuid),
    Column("approval_decision_id", Uuid),
    Column("published_by", Uuid),
    Column("published_at", DateTime(timezone=True)),
    Column("status", Text, server_default=FetchedValue()),
    Column("snapshot_format", Text),
    Column("snapshot_hash", CHAR(64)),
    Column("table_hashes", JSONB),
    Column("row_counts", JSONB),
    Column("manifest_bytes", LargeBinary),
    Column("manifest_sha256", CHAR(64)),
)

publication_attempts = Table(
    "publication_attempts",
    app_metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("dataset_version_id", Uuid),
    Column("attempted_by", Uuid),
    Column("attempted_at", DateTime(timezone=True), server_default=FetchedValue()),
    Column("outcome", Text),
    Column("checks", JSONB),
    Column("publication_id", Uuid),
)

published_suppliers = Table(
    "suppliers",
    published_metadata,
    Column("publication_id", Uuid, primary_key=True),
    Column("supplier_id", Text, primary_key=True),
    Column("supplier_name", Text),
    Column("country_code", Text),
    Column("default_currency", Text),
    Column("status", Text),
    Column("active_from", Date),
    Column("active_to", Date),
    Column("tax_id", Text),
)

published_invoices = Table(
    "invoices",
    published_metadata,
    Column("publication_id", Uuid, primary_key=True),
    Column("invoice_id", Text, primary_key=True),
    Column("supplier_id", Text),
    Column("supplier_invoice_number", Text),
    Column("document_type", Text),
    Column("invoice_date", Date),
    Column("due_date", Date),
    Column("currency", Text),
    Column("net_amount", Numeric(18, 2)),
    Column("tax_amount", Numeric(18, 2)),
    Column("gross_amount", Numeric(18, 2)),
    Column("status", Text),
    Column("description", Text),
)

PUBLISHED_TABLES = {"suppliers": published_suppliers, "invoices": published_invoices}
