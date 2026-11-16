"""Read models that combine modules. Only the composition layer may do this (ARD §6.2)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection

from sentinel.ingestion import service as ingestion
from sentinel.publication import service as publication
from sentinel.review import service as review
from sentinel.shared.authz import Principal
from sentinel.validation import service as validation


def with_state(conn: Connection, version: dict[str, Any] | None) -> dict[str, Any] | None:
    """Add the derived workflow state (FS §2.1) and the current run's finding counts.

    Evaluated in the FS order: SUPERSEDED, PUBLISHED, APPROVED, IN_REVIEW, then validation.
    """
    if version is None:
        return None
    version_id = UUID(version["id"])
    state, counts = validation.version_state(conn, version_id, version["status"])
    publication_ref = publication.publication_for_version(conn, version_id)
    if publication_ref is not None and state != "SUPERSEDED":
        state = "PUBLISHED"
    elif state == "VALIDATED":
        state = review.review_state(conn, version_id) or state
    return {
        **version,
        "derived_state": state,
        "finding_counts": counts,
        "publication_ref": publication_ref,
    }


def review_summary_view(principal: Principal, conn: Connection, version_id: UUID) -> dict[str, Any]:
    version = with_state(conn, ingestion.get_version(principal, conn, version_id))
    return {
        "version": version,
        **review.review_summary(principal, conn, version_id),
        # The checklist comes from the same function that publish uses (PUB-002).
        "eligibility": publication.evaluate_eligibility(principal, conn, version_id),
    }
