"""Audit service (FR-015).

`record` must be called with the same connection as the state change it describes, so both
commit or roll back together. Payloads carry identifiers, counts and outcomes only — never data
cell values, passwords or tokens.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, func, insert, select

from sentinel.audit.tables import events
from sentinel.shared.authz import Permission, Principal, require
from sentinel.shared.context import current_correlation_id

MAX_PAGE = 200


def record(
    conn: Connection,
    *,
    actor: Principal | None,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: Mapping[str, Any] | None = None,
    dataset_version_id: UUID | None = None,
) -> None:
    """Append one audit event. `actor=None` records a SYSTEM event."""
    conn.execute(
        insert(events).values(
            actor_kind="USER" if actor is not None else "SYSTEM",
            actor_user_id=actor.user_id if actor is not None else None,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            dataset_version_id=dataset_version_id,
            payload=dict(payload or {}),
            correlation_id=current_correlation_id(),
        )
    )


@dataclass(frozen=True)
class AuditFilters:
    dataset_version_id: UUID | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    actor_user_id: UUID | None = None
    event_type: str | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None


def list_events(
    principal: Principal,
    conn: Connection,
    filters: AuditFilters,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Chronological (ascending id) filtered view of the audit trail (FR-015.5)."""
    require(principal, Permission.READ)
    limit = max(1, min(limit, MAX_PAGE))
    offset = max(0, offset)

    query = select(events)
    if filters.dataset_version_id is not None:
        query = query.where(events.c.dataset_version_id == filters.dataset_version_id)
    if filters.entity_type is not None:
        query = query.where(events.c.entity_type == filters.entity_type)
    if filters.entity_id is not None:
        query = query.where(events.c.entity_id == filters.entity_id)
    if filters.actor_user_id is not None:
        query = query.where(events.c.actor_user_id == filters.actor_user_id)
    if filters.event_type is not None:
        query = query.where(events.c.event_type == filters.event_type)
    if filters.occurred_from is not None:
        query = query.where(events.c.occurred_at >= filters.occurred_from)
    if filters.occurred_to is not None:
        query = query.where(events.c.occurred_at < filters.occurred_to)

    total = conn.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = conn.execute(query.order_by(events.c.id).limit(limit).offset(offset)).mappings()
    return [dict(r) for r in rows], total
