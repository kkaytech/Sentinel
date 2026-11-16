"""Read models that combine modules. Only the composition layer may do this (ARD §6.2)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection

from sentinel.ingestion import service as ingestion
from sentinel.review import service as review
from sentinel.shared.authz import Principal
from sentinel.validation import service as validation


def with_state(conn: Connection, version: dict[str, Any] | None) -> dict[str, Any] | None:
    """Add the derived workflow state (FS §2.1) and the current run's finding counts.

    PUBLISHED arrives with M1 step 5.
    """
    if version is None:
        return None
    version_id = UUID(version["id"])
    state, counts = validation.version_state(conn, version_id, version["status"])
    if state == "VALIDATED":
        state = review.review_state(conn, version_id) or state
    return {**version, "derived_state": state, "finding_counts": counts}


def review_summary_view(principal: Principal, conn: Connection, version_id: UUID) -> dict[str, Any]:
    version = with_state(conn, ingestion.get_version(principal, conn, version_id))
    return {"version": version, **review.review_summary(principal, conn, version_id)}
