"""Read models that combine modules. Only the composition layer may do this (ARD §6.2)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection

from sentinel.validation import service as validation


def with_state(conn: Connection, version: dict[str, Any] | None) -> dict[str, Any] | None:
    """Add the derived workflow state (FS §2.1) and the current run's finding counts.

    The review and publication states (IN_REVIEW, APPROVED, PUBLISHED) arrive with M1 steps
    4 and 5.
    """
    if version is None:
        return None
    state, counts = validation.version_state(conn, UUID(version["id"]), version["status"])
    return {**version, "derived_state": state, "finding_counts": counts}
