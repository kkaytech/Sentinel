"""Issues, waivers, review and approval (FR-010, FR-013, FR-014; FS §2.3-§2.6, §6).

Every decision stores the binding tuple (version, content hash, run, rule set) and is valid
only while that tuple is current. Stored STALE statuses are for display and audit; the
publication gate recomputes currency itself (ADR-013).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, func, insert, select, update

from sentinel import audit
from sentinel.identity.tables import users
from sentinel.impact import service as impact
from sentinel.ingestion.tables import dataset_periods, dataset_versions
from sentinel.review.tables import (
    approval_decisions,
    issue_notes,
    issues,
    review_requests,
    waiver_decisions,
    waivers,
)
from sentinel.shared.authz import Permission, Principal, require
from sentinel.shared.errors import SentinelError, not_found, validation_error
from sentinel.validation import service as validation
from sentinel.validation.engine import RunOutcome
from sentinel.validation.tables import findings, validation_runs

WAIVER_CATEGORIES = ("FALSE_POSITIVE", "KNOWN_SOURCE_LIMITATION", "IMMATERIAL", "OTHER")
MIN_JUSTIFICATION = 30
# FS §2.3: what a user can do next from each issue state.
ISSUE_TRANSITIONS = {
    "OPEN": ["WAIVER_REQUESTED"],
    "WAIVER_REQUESTED": ["WAIVED", "OPEN"],
    "WAIVED": [],
    "CLOSED_NOT_CURRENT": [],
}


@dataclass(frozen=True)
class BindingTuple:
    dataset_version_id: UUID
    content_hash: str
    validation_run_id: UUID
    rule_set_version_id: UUID

    def columns(self) -> dict[str, Any]:
        return {
            "dataset_version_id": self.dataset_version_id,
            "content_hash": self.content_hash,
            "validation_run_id": self.validation_run_id,
            "rule_set_version_id": self.rule_set_version_id,
        }

    def matches(self, row: Any) -> bool:
        return all(getattr(row, name) == value for name, value in self.columns().items())


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


def _invalid_transition(what: str, state: str, allowed: list[str]) -> SentinelError:
    return SentinelError(
        409, "INVALID_TRANSITION", f"The {what} is {state}; this action is not available.",
        {"current": state, "allowed_transitions": allowed},
    )  # fmt: skip


def _stale(message: str) -> SentinelError:
    return SentinelError(409, "STALE_REVIEW", message)


def _names(conn: Connection, ids: set[UUID | None]) -> dict[UUID, str]:
    wanted = [i for i in ids if i is not None]
    if not wanted:
        return {}
    rows = conn.execute(select(users.c.id, users.c.display_name).where(users.c.id.in_(wanted)))
    return {r.id: r.display_name for r in rows}


def _person(names: dict[UUID, str], user_id: UUID | None) -> dict[str, str] | None:
    if user_id is None:
        return None
    return {"id": str(user_id), "display_name": names.get(user_id, "")}


def current_tuple(conn: Connection, version_id: UUID) -> BindingTuple | None:
    """The current binding tuple, or None when the version has no current run (BR-003)."""
    version = conn.execute(
        select(dataset_versions.c.status, dataset_versions.c.content_hash).where(
            dataset_versions.c.id == version_id
        )
    ).one_or_none()
    if version is None or version.status != "ACTIVE":
        return None
    run_id = validation.current_run_id(conn, version_id)
    if run_id is None:
        return None
    rule_set = conn.execute(
        select(validation_runs.c.rule_set_version_id).where(validation_runs.c.id == run_id)
    ).scalar_one()
    return BindingTuple(version_id, version.content_hash, run_id, rule_set)


# ---- issue creation (post-step of a validation run) ------------------------------------------
def create_issues(conn: Connection, outcome: RunOutcome) -> None:
    """One issue per BLOCKING or WARNING finding (FR-010.1). INFO findings create none."""
    rows = conn.execute(
        select(findings.c.id, findings.c.rule_id, findings.c.severity, findings.c.waivable)
        .where(
            findings.c.run_id == outcome.run_id, findings.c.severity.in_(["BLOCKING", "WARNING"])
        )
        .order_by(findings.c.rule_id)
    ).all()
    if not rows:
        return
    conn.execute(
        insert(issues),
        [
            {
                "finding_id": r.id,
                "run_id": outcome.run_id,
                "dataset_version_id": outcome.ctx.version_id,
                "rule_id": r.rule_id,
                "severity": r.severity,
                "waivable": r.waivable,
            }
            for r in rows
        ],
    )
    audit.record(
        conn,
        actor=None,
        event_type="ISSUES_OPENED",
        entity_type="validation_run",
        entity_id=str(outcome.run_id),
        dataset_version_id=outcome.ctx.version_id,
        payload={"count": len(rows)},
    )


# ---- staleness propagation (FS §2.6) ---------------------------------------------------------
def _propagate(
    conn: Connection, reason: str, issue_filter: Any, waiver_filter: Any, review_filter: Any
) -> dict[str, int]:
    closed = conn.execute(
        update(issues)
        .where(issues.c.state != "CLOSED_NOT_CURRENT", issue_filter)
        .values(state="CLOSED_NOT_CURRENT", state_changed_at=func.now())
        .returning(issues.c.dataset_version_id)
    ).all()
    for version_id in sorted({r.dataset_version_id for r in closed}, key=str):
        audit.record(
            conn,
            actor=None,
            event_type="ISSUES_CLOSED_NOT_CURRENT",
            entity_type="dataset_version",
            entity_id=str(version_id),
            dataset_version_id=version_id,
            payload={"reason": reason,
                     "count": sum(1 for r in closed if r.dataset_version_id == version_id)},
        )  # fmt: skip
    stale_waivers = conn.execute(
        update(waivers)
        .where(waivers.c.status.in_(["REQUESTED", "GRANTED"]), waiver_filter)
        .values(status="STALE", stale_reason=reason)
        .returning(waivers.c.id, waivers.c.dataset_version_id)
    ).all()
    stale_reviews = conn.execute(
        update(review_requests)
        .where(review_requests.c.status.in_(["OPEN", "APPROVED"]), review_filter)
        .values(status="STALE", stale_reason=reason, closed_at=func.now())
        .returning(review_requests.c.id, review_requests.c.dataset_version_id)
    ).all()
    for kind, rows in (("waiver", stale_waivers), ("review_request", stale_reviews)):
        for row in rows:
            audit.record(
                conn,
                actor=None,
                event_type=f"{kind.upper()}_STALE",
                entity_type=kind,
                entity_id=str(row.id),
                dataset_version_id=row.dataset_version_id,
                payload={"reason": reason},
            )
    return {"issues": len(closed), "waivers": len(stale_waivers),
            "review_requests": len(stale_reviews)}  # fmt: skip


def on_versions_superseded(conn: Connection, *, version_ids: list[UUID]) -> None:
    _propagate(
        conn,
        "VERSION_SUPERSEDED",
        issues.c.dataset_version_id.in_(version_ids),
        waivers.c.dataset_version_id.in_(version_ids),
        review_requests.c.dataset_version_id.in_(version_ids),
    )


def on_run_started(conn: Connection, *, version_id: UUID, run_id: UUID) -> None:
    _propagate(
        conn,
        "NEW_RUN",
        (issues.c.dataset_version_id == version_id) & (issues.c.run_id != run_id),
        (waivers.c.dataset_version_id == version_id) & (waivers.c.validation_run_id != run_id),
        (review_requests.c.dataset_version_id == version_id)
        & (review_requests.c.validation_run_id != run_id),
    )


def on_rule_set_activated(conn: Connection, *, dataset_key: str, rule_set_version_id: UUID) -> None:
    in_dataset = select(dataset_versions.c.id).where(
        dataset_versions.c.dataset_period_id.in_(
            select(dataset_periods.c.id).where(dataset_periods.c.dataset_key == dataset_key)
        )
    )
    old_runs = select(validation_runs.c.id).where(
        validation_runs.c.dataset_version_id.in_(in_dataset),
        validation_runs.c.rule_set_version_id != rule_set_version_id,
    )
    _propagate(
        conn,
        "RULE_SET_CHANGED",
        issues.c.run_id.in_(old_runs),
        waivers.c.dataset_version_id.in_(in_dataset)
        & (waivers.c.rule_set_version_id != rule_set_version_id),
        review_requests.c.dataset_version_id.in_(in_dataset)
        & (review_requests.c.rule_set_version_id != rule_set_version_id),
    )


# ---- issues, notes and waivers ---------------------------------------------------------------
def _issue_row(conn: Connection, issue_id: UUID, *, lock: bool = False) -> Any:
    query = select(issues).where(issues.c.id == issue_id)
    row = conn.execute(query.with_for_update() if lock else query).one_or_none()
    if row is None:
        raise not_found("Issue")
    return row


def _waiver_views(conn: Connection, where: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        select(
            waivers,
            issues.c.rule_id,
            waiver_decisions.c.decision,
            waiver_decisions.c.decided_by,
            waiver_decisions.c.comment,
            waiver_decisions.c.decided_at,
        )
        .select_from(
            waivers.join(issues, issues.c.id == waivers.c.issue_id).outerjoin(
                waiver_decisions, waiver_decisions.c.waiver_id == waivers.c.id
            )
        )
        .where(where)
        .order_by(waivers.c.requested_at, waivers.c.id)
    ).all()
    names = _names(conn, {r.requested_by for r in rows} | {r.decided_by for r in rows})
    return [
        {
            "id": str(r.id),
            "issue_id": str(r.issue_id),
            "rule_id": r.rule_id,
            "status": r.status,
            "stale_reason": r.stale_reason,
            "category": r.category,
            "justification": r.justification,
            "requested_by": _person(names, r.requested_by),
            "requested_at": _iso(r.requested_at),
            "decision": r.decision,
            "decided_by": _person(names, r.decided_by),
            "decided_at": _iso(r.decided_at),
            "comment": r.comment,
            "validation_run_id": str(r.validation_run_id),
        }
        for r in rows
    ]


def _issue_view(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "finding_id": str(row.finding_id),
        "run_id": str(row.run_id),
        "dataset_version_id": str(row.dataset_version_id),
        "rule_id": row.rule_id,
        "severity": row.severity,
        "waivable": row.waivable,
        "state": row.state,
        "state_changed_at": _iso(row.state_changed_at),
        "allowed_transitions": ISSUE_TRANSITIONS[row.state] if row.waivable else [],
    }


def list_issues(
    principal: Principal, conn: Connection, run_id: UUID, *,
    severity: str | None = None, state: str | None = None,
) -> list[dict[str, Any]]:  # fmt: skip
    require(principal, Permission.READ)
    query = (
        select(issues, findings.c.message, findings.c.failing_count)
        .select_from(issues.join(findings, findings.c.id == issues.c.finding_id))
        .where(issues.c.run_id == run_id)
    )
    if severity is not None:
        query = query.where(issues.c.severity == severity)
    if state is not None:
        query = query.where(issues.c.state == state)
    rows = conn.execute(query.order_by(issues.c.severity, issues.c.rule_id)).all()
    return [
        {**_issue_view(r), "message": r.message, "failing_count": r.failing_count} for r in rows
    ]


def get_issue(principal: Principal, conn: Connection, issue_id: UUID) -> dict[str, Any]:
    require(principal, Permission.READ)
    row = _issue_row(conn, issue_id)
    notes = conn.execute(
        select(issue_notes)
        .where(issue_notes.c.issue_id == issue_id)
        .order_by(issue_notes.c.created_at, issue_notes.c.id)
    ).all()
    names = _names(conn, {n.author_id for n in notes})
    return {
        "issue": _issue_view(row),
        "finding": validation.get_finding(principal, conn, row.finding_id),
        "notes": [
            {
                "id": str(n.id),
                "author": _person(names, n.author_id),
                "body": n.body,
                "created_at": _iso(n.created_at),
            }
            for n in notes
        ],
        "waivers": _waiver_views(conn, waivers.c.issue_id == issue_id),
    }


def add_note(principal: Principal, conn: Connection, issue_id: UUID, body: str) -> dict[str, Any]:
    """Append-only note, allowed in any issue state (FR-010)."""
    require(principal, Permission.ADD_NOTE)
    issue = _issue_row(conn, issue_id)
    body = body.strip()
    if not 1 <= len(body) <= 5000:
        raise validation_error("A note must be between 1 and 5000 characters.", {"field": "body"})
    row = conn.execute(
        insert(issue_notes)
        .values(issue_id=issue_id, author_id=principal.user_id, body=body)
        .returning(issue_notes.c.id, issue_notes.c.created_at)
    ).one()
    audit.record(
        conn,
        actor=principal,
        event_type="ISSUE_NOTE_ADDED",
        entity_type="issue",
        entity_id=str(issue_id),
        dataset_version_id=issue.dataset_version_id,
        payload={"note_id": str(row.id), "length": len(body)},
    )
    return {
        "id": str(row.id),
        "author": {"id": str(principal.user_id), "display_name": principal.display_name},
        "body": body,
        "created_at": _iso(row.created_at),
    }


def _set_issue_state(conn: Connection, issue_id: UUID, state: str) -> None:
    conn.execute(
        update(issues)
        .where(issues.c.id == issue_id)
        .values(state=state, state_changed_at=func.now())
    )


def request_waiver(
    principal: Principal, conn: Connection, issue_id: UUID, category: str, justification: str
) -> dict[str, Any]:
    require(principal, Permission.REQUEST_WAIVER)
    issue = _issue_row(conn, issue_id, lock=True)
    if issue.state != "OPEN":
        raise _invalid_transition("issue", issue.state, ISSUE_TRANSITIONS[issue.state])
    if issue.severity != "BLOCKING":
        raise SentinelError(
            409, "WAIVER_NOT_APPLICABLE",
            "Warnings are acknowledged at approval; they are not waived.",
        )  # fmt: skip
    if not issue.waivable:
        raise SentinelError(
            409, "RULE_NOT_WAIVABLE",
            "This rule cannot be waived. The data must be corrected and uploaded again.",
        )  # fmt: skip
    justification = justification.strip()
    if category not in WAIVER_CATEGORIES:
        raise validation_error("Choose a waiver reason category.", {"field": "category"})
    if len(justification) < MIN_JUSTIFICATION:
        raise validation_error(
            f"The justification must be at least {MIN_JUSTIFICATION} characters.",
            {"field": "justification"},
        )
    binding = current_tuple(conn, issue.dataset_version_id)
    if binding is None or binding.validation_run_id != issue.run_id:
        raise _stale("This issue belongs to a validation run that is no longer current.")
    waiver_id = conn.execute(
        insert(waivers)
        .values(
            issue_id=issue_id,
            category=category,
            justification=justification,
            requested_by=principal.user_id,
            **binding.columns(),
        )
        .returning(waivers.c.id)
    ).scalar_one()
    _set_issue_state(conn, issue_id, "WAIVER_REQUESTED")
    audit.record(
        conn,
        actor=principal,
        event_type="WAIVER_REQUESTED",
        entity_type="waiver",
        entity_id=str(waiver_id),
        dataset_version_id=issue.dataset_version_id,
        payload={"issue_id": str(issue_id), "rule_id": issue.rule_id, "category": category},
    )
    return _waiver_views(conn, waivers.c.id == waiver_id)[0]


def decide_waiver(
    principal: Principal, conn: Connection, waiver_id: UUID, decision: str, comment: str | None
) -> dict[str, Any]:
    require(principal, Permission.DECIDE_WAIVER)
    waiver = conn.execute(
        select(waivers).where(waivers.c.id == waiver_id).with_for_update()
    ).one_or_none()
    if waiver is None:
        raise not_found("Waiver")
    if waiver.requested_by == principal.user_id:
        raise SentinelError(
            403, "SEGREGATION_OF_DUTIES", "You cannot decide a waiver that you requested."
        )
    if waiver.status != "REQUESTED":
        raise _invalid_transition("waiver", waiver.status, [])
    comment = (comment or "").strip() or None
    if decision == "DENY" and comment is None:
        raise validation_error("A comment is required when denying a waiver.", {"field": "comment"})
    binding = current_tuple(conn, waiver.dataset_version_id)
    if binding is None or not binding.matches(waiver):
        raise _stale("The data or its validation has changed since this waiver was requested.")
    conn.execute(
        insert(waiver_decisions).values(
            waiver_id=waiver_id, decision=decision, decided_by=principal.user_id, comment=comment
        )
    )
    granted = decision == "GRANT"
    conn.execute(
        update(waivers)
        .where(waivers.c.id == waiver_id)
        .values(status="GRANTED" if granted else "DENIED")
    )
    _set_issue_state(conn, waiver.issue_id, "WAIVED" if granted else "OPEN")
    audit.record(
        conn,
        actor=principal,
        event_type="WAIVER_GRANTED" if granted else "WAIVER_DENIED",
        entity_type="waiver",
        entity_id=str(waiver_id),
        dataset_version_id=waiver.dataset_version_id,
        payload={"issue_id": str(waiver.issue_id)},
    )
    return _waiver_views(conn, waivers.c.id == waiver_id)[0]


# ---- review and approval ---------------------------------------------------------------------
def _issue_counts(conn: Connection, run_id: UUID) -> dict[str, dict[str, int]]:
    rows = conn.execute(
        select(issues.c.severity, issues.c.state, func.count().label("n"))
        .where(issues.c.run_id == run_id)
        .group_by(issues.c.severity, issues.c.state)
    ).all()
    counts: dict[str, dict[str, int]] = {"BLOCKING": {}, "WARNING": {}}
    for row in sorted(rows, key=lambda r: (r.severity, r.state)):
        counts[row.severity][row.state] = row.n
    return counts


def open_warning_count(conn: Connection, run_id: UUID) -> int:
    count: int = conn.execute(
        select(func.count())
        .select_from(issues)
        .where(issues.c.run_id == run_id, issues.c.severity == "WARNING", issues.c.state == "OPEN")
    ).scalar_one()
    return count


def unwaived_blocking(conn: Connection, run_id: UUID) -> list[Any]:
    """BLOCKING issues of the run that are not WAIVED (for the banner and for eligibility)."""
    return list(
        conn.execute(
            select(issues.c.id, issues.c.rule_id, issues.c.waivable, issues.c.state)
            .where(
                issues.c.run_id == run_id,
                issues.c.severity == "BLOCKING",
                issues.c.state != "WAIVED",
            )
            .order_by(issues.c.rule_id)
        ).all()
    )


def _summary(principal: Principal, conn: Connection, run_id: UUID) -> dict[str, Any]:
    """The reviewable facts of a run: what a submission freezes and what the page shows live."""
    run_impact = impact.run_impact(principal, conn, run_id)
    granted = _waiver_views(
        conn, (waivers.c.validation_run_id == run_id) & (waivers.c.status == "GRANTED")
    )
    return {
        "validation_run_id": str(run_id),
        "issue_counts": _issue_counts(conn, run_id),
        "impact_totals": run_impact["totals"],
        "kpis": run_impact["kpis"],
        "granted_waivers": [
            {k: w[k] for k in ("id", "rule_id", "category", "justification")} for w in granted
        ],
    }


def submit_review(
    principal: Principal, conn: Connection, version_id: UUID, note: str
) -> dict[str, Any]:
    require(principal, Permission.SUBMIT_REVIEW)
    version = conn.execute(
        select(dataset_versions.c.status)
        .where(dataset_versions.c.id == version_id)
        .with_for_update()
    ).one_or_none()
    if version is None:
        raise SentinelError(404, "VERSION_NOT_FOUND", "Dataset version not found.")
    if version.status != "ACTIVE":
        raise SentinelError(409, "VERSION_SUPERSEDED", "This version has been superseded.")
    binding = current_tuple(conn, version_id)
    if binding is None:
        raise SentinelError(
            409, "NO_CURRENT_VALIDATION",
            "Run validation under the active rule set before submitting for review.",
        )  # fmt: skip
    already_open = conn.execute(
        select(func.count())
        .select_from(review_requests)
        .where(
            review_requests.c.dataset_version_id == version_id, review_requests.c.status == "OPEN"
        )
    ).scalar_one()
    if already_open:
        raise SentinelError(409, "REVIEW_ALREADY_OPEN", "A review request is already open.")
    note = note.strip()
    if not note:
        raise validation_error("A note for the approver is required.", {"field": "note"})
    request_id = conn.execute(
        insert(review_requests)
        .values(
            submitted_by=principal.user_id,
            note=note,
            snapshot=_summary(principal, conn, binding.validation_run_id),
            **binding.columns(),
        )
        .returning(review_requests.c.id)
    ).scalar_one()
    audit.record(
        conn,
        actor=principal,
        event_type="REVIEW_SUBMITTED",
        entity_type="review_request",
        entity_id=str(request_id),
        dataset_version_id=version_id,
        payload={"validation_run_id": str(binding.validation_run_id)},
    )
    return _request_views(conn, review_requests.c.id == request_id)[0]


def decide_review(
    principal: Principal, conn: Connection, request_id: UUID, decision: str,
    comment: str | None, acknowledged_warning_count: int | None,
) -> dict[str, Any]:  # fmt: skip
    require(principal, Permission.DECIDE_REVIEW)
    request = conn.execute(
        select(review_requests).where(review_requests.c.id == request_id).with_for_update()
    ).one_or_none()
    if request is None:
        raise not_found("Review request")
    if request.submitted_by == principal.user_id:
        raise SentinelError(
            403, "SEGREGATION_OF_DUTIES", "You cannot decide a review that you submitted."
        )
    if request.status != "OPEN":
        raise _invalid_transition("review request", request.status, [])
    binding = current_tuple(conn, request.dataset_version_id)
    if binding is None or not binding.matches(request):
        raise _stale("The data or its validation has changed since this review was submitted.")
    comment = (comment or "").strip() or None
    approve = decision == "APPROVE"
    if approve:
        warnings = open_warning_count(conn, request.validation_run_id)
        if acknowledged_warning_count != warnings:
            raise SentinelError(
                409, "WARNING_COUNT_MISMATCH",
                f"Approval must acknowledge the {warnings} open warning(s).",
                {"open_warning_count": warnings},
            )  # fmt: skip
    elif comment is None:
        raise validation_error("A comment is required when rejecting.", {"field": "comment"})
    conn.execute(
        insert(approval_decisions).values(
            review_request_id=request_id,
            decision=decision,
            decided_by=principal.user_id,
            comment=comment,
            acknowledged_warning_count=acknowledged_warning_count if approve else None,
            **binding.columns(),
        )
    )
    conn.execute(
        update(review_requests)
        .where(review_requests.c.id == request_id)
        .values(status="APPROVED" if approve else "REJECTED", closed_at=func.now())
    )
    audit.record(
        conn,
        actor=principal,
        event_type="REVIEW_APPROVED" if approve else "REVIEW_REJECTED",
        entity_type="review_request",
        entity_id=str(request_id),
        dataset_version_id=request.dataset_version_id,
        payload={"acknowledged_warning_count": acknowledged_warning_count if approve else None},
    )
    return _request_views(conn, review_requests.c.id == request_id)[0]


def _request_views(conn: Connection, where: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        select(
            review_requests,
            approval_decisions.c.decision,
            approval_decisions.c.decided_by,
            approval_decisions.c.comment,
            approval_decisions.c.acknowledged_warning_count,
            approval_decisions.c.decided_at,
        )
        .select_from(
            review_requests.outerjoin(
                approval_decisions, approval_decisions.c.review_request_id == review_requests.c.id
            )
        )
        .where(where)
        .order_by(review_requests.c.submitted_at.desc(), review_requests.c.id)
    ).all()
    names = _names(conn, {r.submitted_by for r in rows} | {r.decided_by for r in rows})
    return [
        {
            "id": str(r.id),
            "dataset_version_id": str(r.dataset_version_id),
            "validation_run_id": str(r.validation_run_id),
            "status": r.status,
            "stale_reason": r.stale_reason,
            "note": r.note,
            "submitted_by": _person(names, r.submitted_by),
            "submitted_at": _iso(r.submitted_at),
            "snapshot": r.snapshot,
            "decision": r.decision,
            "decided_by": _person(names, r.decided_by),
            "decided_at": _iso(r.decided_at),
            "comment": r.comment,
            "acknowledged_warning_count": r.acknowledged_warning_count,
        }
        for r in rows
    ]


def list_review_requests(
    principal: Principal, conn: Connection, version_id: UUID
) -> list[dict[str, Any]]:
    require(principal, Permission.READ)
    return _request_views(conn, review_requests.c.dataset_version_id == version_id)


def review_state(conn: Connection, version_id: UUID) -> str | None:
    """APPROVED (bound to the current tuple), IN_REVIEW, or None (FS §2.1)."""
    binding = current_tuple(conn, version_id)
    rows = conn.execute(
        select(review_requests).where(
            review_requests.c.dataset_version_id == version_id,
            review_requests.c.status.in_(["OPEN", "APPROVED"]),
        )
    ).all()
    if binding is not None and any(r.status == "APPROVED" and binding.matches(r) for r in rows):
        return "APPROVED"
    return "IN_REVIEW" if any(r.status == "OPEN" for r in rows) else None


def review_summary(principal: Principal, conn: Connection, version_id: UUID) -> dict[str, Any]:
    """Everything the review page shows: the latest submission's frozen snapshot, the live
    state, the differences between them, waivers and history (FS §6)."""
    require(principal, Permission.READ)
    history = list_review_requests(principal, conn, version_id)
    binding = current_tuple(conn, version_id)
    live = _summary(principal, conn, binding.validation_run_id) if binding else None
    latest = history[0] if history else None
    snapshot = latest["snapshot"] if latest else None
    differences = []
    if live is not None and snapshot is not None:
        differences = [key for key in live if snapshot.get(key) != live[key]]
    run_id = binding.validation_run_id if binding else None
    blockers = unwaived_blocking(conn, run_id) if run_id else []
    return {
        "current_run_id": str(run_id) if run_id else None,
        "request": latest,
        "snapshot": snapshot,
        "live": live,
        "differences": differences,
        "issues": list_issues(principal, conn, run_id) if run_id else [],
        "waivers": _waiver_views(conn, waivers.c.dataset_version_id == version_id),
        "history": history,
        "open_warning_count": open_warning_count(conn, run_id) if run_id else 0,
        "blocking_unwaived_count": len(blockers),
        "blocking_non_waivable_count": sum(1 for b in blockers if not b.waivable),
    }
