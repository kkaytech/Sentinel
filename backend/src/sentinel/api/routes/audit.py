"""Audit trail viewer (FR-015). Read-only: no PUT, PATCH or DELETE exists (FR-015.4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Engine

from sentinel import audit
from sentinel.api.deps import AuthContext, current_auth, get_engine, protected
from sentinel.shared.authz import Permission
from sentinel.shared.db import unit_of_work

router = APIRouter(prefix="/api/v1")


def _serialise(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event["id"],
        "event_id": str(event["event_id"]),
        "occurred_at": event["occurred_at"].isoformat(),
        "actor_kind": event["actor_kind"],
        "actor_user_id": str(event["actor_user_id"]) if event["actor_user_id"] else None,
        "event_type": event["event_type"],
        "entity_type": event["entity_type"],
        "entity_id": event["entity_id"],
        "dataset_version_id": (
            str(event["dataset_version_id"]) if event["dataset_version_id"] else None
        ),
        "payload": event["payload"],
        "correlation_id": event["correlation_id"],
    }


@router.get("/audit/events", **protected(Permission.READ))
def get_events(
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
    version_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_id: UUID | None = None,
    event_type: str | None = None,
    occurred_from: datetime | None = Query(default=None, alias="from"),  # noqa: B008
    occurred_to: datetime | None = Query(default=None, alias="to"),  # noqa: B008
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    filters = audit.AuditFilters(
        dataset_version_id=version_id,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_user_id=actor_id,
        event_type=event_type,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )
    with unit_of_work(engine) as conn:
        rows, total = audit.list_events(ctx.principal, conn, filters, limit=limit, offset=offset)
    return {
        "items": [_serialise(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
