"""Table definitions for queries. The schema itself is owned by migrations (0008)."""

from __future__ import annotations

from sqlalchemy import (
    CHAR,
    Boolean,
    Column,
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


def _tuple() -> list[Column[object]]:
    return [
        Column("dataset_version_id", Uuid),
        Column("content_hash", CHAR(64)),
        Column("validation_run_id", Uuid),
        Column("rule_set_version_id", Uuid),
    ]


def _ts(name: str) -> Column[object]:
    return Column(name, DateTime(timezone=True), server_default=FetchedValue())


issues = Table(
    "issues",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("finding_id", Uuid),
    Column("run_id", Uuid),
    Column("dataset_version_id", Uuid),
    Column("rule_id", Text),
    Column("severity", Text),
    Column("waivable", Boolean),
    Column("state", Text, server_default=FetchedValue()),
    _ts("state_changed_at"),
    _ts("created_at"),
)

issue_notes = Table(
    "issue_notes",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("issue_id", Uuid),
    Column("author_id", Uuid),
    Column("body", Text),
    _ts("created_at"),
)

waivers = Table(
    "waivers",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("issue_id", Uuid),
    *_tuple(),
    Column("category", Text),
    Column("justification", Text),
    Column("requested_by", Uuid),
    _ts("requested_at"),
    Column("status", Text, server_default=FetchedValue()),
    Column("stale_reason", Text),
)

waiver_decisions = Table(
    "waiver_decisions",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("waiver_id", Uuid),
    Column("decision", Text),
    Column("decided_by", Uuid),
    Column("comment", Text),
    _ts("decided_at"),
)

review_requests = Table(
    "review_requests",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    *_tuple(),
    Column("submitted_by", Uuid),
    _ts("submitted_at"),
    Column("note", Text),
    Column("snapshot", JSONB),
    Column("status", Text, server_default=FetchedValue()),
    Column("stale_reason", Text),
    Column("closed_at", DateTime(timezone=True)),
)

approval_decisions = Table(
    "approval_decisions",
    metadata,
    Column("id", Uuid, primary_key=True, server_default=FetchedValue()),
    Column("review_request_id", Uuid),
    *_tuple(),
    Column("decision", Text),
    Column("decided_by", Uuid),
    Column("comment", Text),
    Column("acknowledged_warning_count", Integer),
    _ts("decided_at"),
)
