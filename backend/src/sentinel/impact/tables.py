"""Table definitions for queries. The schema itself is owned by migrations (0007)."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, FetchedValue, Integer, MetaData, Numeric, Table, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData(schema="app")

impact_figures = Table(
    "impact_figures",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("finding_id", Uuid),
    Column("category", Text),
    Column("currency", Text),
    Column("amount", Numeric(18, 2)),
    Column("quantifiable", Boolean),
    Column("record_count", Integer),
    Column("formula_id", Text),
    Column("assumption", Text),
    Column("inputs", JSONB),
)

run_impact_totals = Table(
    "run_impact_totals",
    metadata,
    Column("run_id", Uuid, primary_key=True),
    Column("category", Text, primary_key=True),
    Column("currency", Text, primary_key=True),
    Column("amount", Numeric(18, 2)),
    Column("record_count", Integer),
    Column("unquantifiable_count", Integer),
)

kpi_values = Table(
    "kpi_values",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("run_id", Uuid),
    Column("kpi_id", Text),
    Column("scope", Text),
    Column("finding_id", Uuid),
    Column("currency", Text),
    Column("supplier_id", Text),
    Column("value", Numeric(20, 2)),
    Column("delta_abs", Numeric(20, 2)),
    Column("delta_pct", Numeric(9, 2)),
    Column("direction", Text),
    Column("assumption", Text),
)
