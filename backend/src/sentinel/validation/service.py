"""Validation runs: commands and queries (FR-006, FR-009; FS §2.2, ARD §8.4).

A run is committed as RUNNING first. Everything it produces is then written, and the run is
marked COMPLETED, in one transaction. Any exception rolls that transaction back and a separate
one marks the run ERROR, so a crash can never look like "no issues" (fail closed).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, func, insert, select, text, update

from sentinel import __version__, audit
from sentinel.config import service as config_service
from sentinel.ingestion.tables import dataset_periods, dataset_versions, version_rows
from sentinel.shared import hooks
from sentinel.shared.authz import Permission, Principal, require
from sentinel.shared.csvsafe import neutralise
from sentinel.shared.db import unit_of_work
from sentinel.shared.errors import SentinelError, not_found
from sentinel.validation import engine as rule_engine
from sentinel.validation.engine import RunOutcome
from sentinel.validation.rules import RunContext
from sentinel.validation.tables import finding_records, findings, validation_runs

PostStep = Callable[[Connection, RunOutcome], None]
# Planner settings for the completion transaction only (ARD §8.4). Constants, never user input.
RUN_SETTINGS = (
    # PoC-1: set-level rules and the KPI aggregate spill sorts to disk at the 4 MB default.
    text("SET LOCAL work_mem = '64MB'"),
    # Each rule query is planned and run once. On postgres:16, JIT compiled most of them
    # with LLVM first, which cost several seconds per query: whole runs took 105-214 s
    # instead of seconds (measured at 100,000 invoices).
    text("SET LOCAL jit = off"),
    # Every rule reads a whole version, so a nested loop is never the right join. Right after
    # a large upload, statistics do not cover the new version yet; PostgreSQL then guesses it
    # is tiny and can choose nested loops. The app role cannot run ANALYZE (it owns no
    # tables), so this setting keeps run time independent of when autovacuum last ran.
    text("SET LOCAL enable_nestloop = off"),
)
SEVERITY_ORDER = {"BLOCKING": 0, "WARNING": 1, "INFO": 2}
MAX_PAGE = 200


def period_bounds(period: str) -> tuple[date, date]:
    year, month = int(period[:4]), int(period[5:])
    following = date(year + (month == 12), month % 12 + 1, 1)
    return date(year, month, 1), following - timedelta(days=1)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


# ---- commands ----------------------------------------------------------------------------
def start_run(principal: Principal, conn: Connection, version_id: UUID) -> UUID:
    """Create a RUNNING run for the active rule set. The caller commits before executing it."""
    require(principal, Permission.RUN_VALIDATION)
    version = conn.execute(
        select(dataset_versions.c.status, dataset_periods.c.dataset_key, dataset_periods.c.period)
        .select_from(
            dataset_versions.join(
                dataset_periods, dataset_periods.c.id == dataset_versions.c.dataset_period_id
            )
        )
        .where(dataset_versions.c.id == version_id)
        .with_for_update(of=dataset_versions)  # serialises concurrent starts on one version
    ).one_or_none()
    if version is None:
        raise SentinelError(404, "VERSION_NOT_FOUND", "Dataset version not found.")
    if version.status != "ACTIVE":
        raise SentinelError(409, "VERSION_SUPERSEDED", "This version has been superseded.")
    running = conn.execute(
        select(func.count())
        .select_from(validation_runs)
        .where(
            validation_runs.c.dataset_version_id == version_id,
            validation_runs.c.status == "RUNNING",
        )
    ).scalar_one()
    if running:
        raise SentinelError(409, "RUN_IN_PROGRESS", "A validation run is already in progress.")
    active = config_service.get_active(conn, version.dataset_key)
    _, period_end = period_bounds(version.period)
    run_id: UUID = conn.execute(
        insert(validation_runs)
        .values(
            dataset_version_id=version_id,
            rule_set_version_id=active.rule_set_version_id,
            engine_version=__version__,
            period=version.period,
            reference_date=period_end + timedelta(days=active.rules.reference_date_offset_days),
            triggered_by=principal.user_id,
        )
        .returning(validation_runs.c.id)
    ).scalar_one()
    hooks.emit(hooks.RUN_STARTED, conn, version_id=version_id, run_id=run_id)
    audit.record(
        conn,
        actor=principal,
        event_type="VALIDATION_RUN_STARTED",
        entity_type="validation_run",
        entity_id=str(run_id),
        dataset_version_id=version_id,
        payload={"rule_set_version_id": str(active.rule_set_version_id)},
    )
    return run_id


def execute_run(
    engine: Engine,
    run_id: UUID,
    *,
    post_steps: Sequence[PostStep] = (),
    key_cap: int = 10_000,
    before_rule: rule_engine.RuleHook | None = None,
) -> str:
    """Execute a RUNNING run and return its final status. Never raises for an engine error."""
    progress: dict[str, str | None] = {"rule_id": None}

    def track(rule: Any) -> None:
        progress["rule_id"] = rule.id
        if before_rule is not None:
            before_rule(rule)

    version_id: UUID | None = None
    try:
        with unit_of_work(engine) as conn:
            for setting in RUN_SETTINGS:
                conn.execute(setting)
            run = conn.execute(select(validation_runs).where(validation_runs.c.id == run_id)).one()
            if run.status != "RUNNING":
                raise SentinelError(409, "INVALID_TRANSITION", "The run is not RUNNING.")
            version_id = run.dataset_version_id
            version = conn.execute(
                select(dataset_versions).where(dataset_versions.c.id == version_id)
            ).one()
            start, end = period_bounds(run.period)
            ctx = RunContext(
                version_id=version.id,
                contract=config_service.get_contract(conn, version.contract_version_id),
                period_start=start,
                period_end=end,
                reference_date=run.reference_date,
            )
            outcome = rule_engine.evaluate_rules(
                conn,
                run_id,
                ctx,
                config_service.get_rule_set(conn, run.rule_set_version_id),
                version.columns,
                version.row_counts,
                key_cap,
                before_rule=track,
            )
            progress["rule_id"] = None
            for step in post_steps:
                step(conn, outcome)
            conn.execute(
                update(validation_runs)
                .where(validation_runs.c.id == run_id)
                .values(
                    status="COMPLETED",
                    finished_at=func.clock_timestamp(),
                    finding_counts=outcome.finding_counts,
                    not_evaluated=outcome.not_evaluated,
                )
            )
            audit.record(
                conn,
                actor=None,
                event_type="VALIDATION_RUN_COMPLETED",
                entity_type="validation_run",
                entity_id=str(run_id),
                dataset_version_id=version_id,
                payload={
                    "finding_counts": outcome.finding_counts,
                    "not_evaluated": len(outcome.not_evaluated),
                },
            )
        return "COMPLETED"
    except Exception as exc:
        # The completion transaction rolled back: no partial findings exist (FR-006.4).
        # Diagnostics carry the exception type and rule only, never data values.
        detail = {"type": type(exc).__name__, "rule_id": progress["rule_id"]}
        with unit_of_work(engine) as conn:
            conn.execute(
                update(validation_runs)
                .where(validation_runs.c.id == run_id, validation_runs.c.status == "RUNNING")
                .values(status="ERROR", finished_at=func.clock_timestamp(), error_detail=detail)
            )
            audit.record(
                conn,
                actor=None,
                event_type="VALIDATION_RUN_FAILED",
                entity_type="validation_run",
                entity_id=str(run_id),
                dataset_version_id=version_id,
                payload=detail,
            )
        return "ERROR"


# ---- current run (BR-003) and derived state (FS §2.1) --------------------------------------
def _latest_run(conn: Connection, version_id: UUID) -> Any:
    return conn.execute(
        select(validation_runs)
        .where(validation_runs.c.dataset_version_id == version_id)
        .order_by(validation_runs.c.started_at.desc(), validation_runs.c.id.desc())
        .limit(1)
    ).one_or_none()


def _active_rule_set(conn: Connection, version_id: UUID) -> UUID:
    key = conn.execute(
        select(dataset_periods.c.dataset_key)
        .select_from(
            dataset_versions.join(
                dataset_periods, dataset_periods.c.id == dataset_versions.c.dataset_period_id
            )
        )
        .where(dataset_versions.c.id == version_id)
    ).scalar_one()
    return config_service.get_active(conn, key).rule_set_version_id


def current_run_id(conn: Connection, version_id: UUID) -> UUID | None:
    """BR-003: the most recent run, only if it COMPLETED under the active rule set."""
    latest = _latest_run(conn, version_id)
    if latest is None or latest.status != "COMPLETED":
        return None
    if latest.rule_set_version_id != _active_rule_set(conn, version_id):
        return None
    run_id: UUID = latest.id
    return run_id


def version_state(conn: Connection, version_id: UUID, status: str) -> tuple[str, dict[str, int]]:
    """The validation part of the derived workflow state, with the current run's counts."""
    empty = dict.fromkeys(SEVERITY_ORDER, 0)
    if status == "SUPERSEDED":
        return "SUPERSEDED", empty
    latest = _latest_run(conn, version_id)
    if latest is None:
        return "INGESTED", empty
    if latest.status == "RUNNING":
        return "VALIDATING", empty
    if latest.status == "ERROR":
        return "VALIDATION_FAILED", empty
    if latest.rule_set_version_id != _active_rule_set(conn, version_id):
        return "INGESTED", empty  # stale validation: there is no current run
    return "VALIDATED", {**empty, **latest.finding_counts}


# ---- queries -----------------------------------------------------------------------------
def _run_view(conn: Connection, row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "dataset_version_id": str(row.dataset_version_id),
        "rule_set_version_id": str(row.rule_set_version_id),
        "engine_version": row.engine_version,
        "period": row.period,
        "reference_date": row.reference_date.isoformat(),
        "status": row.status,
        "is_current": current_run_id(conn, row.dataset_version_id) == row.id,
        "finding_counts": row.finding_counts,
        "not_evaluated": row.not_evaluated or [],
        "error_detail": row.error_detail,
        "triggered_by": str(row.triggered_by),
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
    }


def get_run(principal: Principal, conn: Connection, run_id: UUID) -> dict[str, Any]:
    require(principal, Permission.READ)
    row = conn.execute(select(validation_runs).where(validation_runs.c.id == run_id)).one_or_none()
    if row is None:
        raise not_found("Validation run")
    return _run_view(conn, row)


def list_runs(principal: Principal, conn: Connection, version_id: UUID) -> list[dict[str, Any]]:
    require(principal, Permission.READ)
    rows = conn.execute(
        select(validation_runs)
        .where(validation_runs.c.dataset_version_id == version_id)
        .order_by(validation_runs.c.started_at.desc(), validation_runs.c.id.desc())
    ).all()
    return [_run_view(conn, r) for r in rows]


def _finding_view(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "rule_id": row.rule_id,
        "rule_type": row.rule_type,
        "severity": row.severity,
        "waivable": row.waivable,
        "table": row.table_name,
        "columns": list(row.columns),
        "failing_count": row.failing_count,
        "evaluated_count": row.evaluated_count,
        "truncated": row.truncated,
        "samples": row.samples,
        "message": row.message,
        "details": row.details,
    }


def list_findings(
    principal: Principal, conn: Connection, run_id: UUID, severity: str | None = None
) -> list[dict[str, Any]]:
    """Findings ordered by severity, then rule ID (Doc 4 §3.4)."""
    require(principal, Permission.READ)
    get_run(principal, conn, run_id)
    query = select(findings).where(findings.c.run_id == run_id)
    if severity is not None:
        query = query.where(findings.c.severity == severity)
    rows = conn.execute(query.order_by(findings.c.rule_id)).all()
    return [_finding_view(r) for r in sorted(rows, key=lambda r: SEVERITY_ORDER[r.severity])]


def _finding_row(conn: Connection, finding_id: UUID) -> Any:
    row = conn.execute(select(findings).where(findings.c.id == finding_id)).one_or_none()
    if row is None:
        raise not_found("Finding")
    return row


def get_finding(principal: Principal, conn: Connection, finding_id: UUID) -> dict[str, Any]:
    require(principal, Permission.READ)
    return _finding_view(_finding_row(conn, finding_id))


def _records_query(conn: Connection, finding: Any) -> Any:
    version_id = conn.execute(
        select(validation_runs.c.dataset_version_id).where(validation_runs.c.id == finding.run_id)
    ).scalar_one()
    return (
        select(finding_records, version_rows.c.cells)
        .select_from(
            finding_records.join(
                version_rows,
                (version_rows.c.dataset_version_id == version_id)
                & (version_rows.c.table_name == finding.table_name)
                & (version_rows.c.row_num == finding_records.c.row_num),
            )
        )
        .where(finding_records.c.finding_id == finding.id)
        .order_by(finding_records.c.row_num, finding_records.c.ordinal)
    )


def list_finding_records(
    principal: Principal, conn: Connection, finding_id: UUID, *, limit: int = 50, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    """Drill-down: exactly the records in the finding's key list (FR-009.3)."""
    require(principal, Permission.READ)
    finding = _finding_row(conn, finding_id)
    limit, offset = max(1, min(limit, MAX_PAGE)), max(0, offset)
    total = conn.execute(
        select(func.count())
        .select_from(finding_records)
        .where(finding_records.c.finding_id == finding_id)
    ).scalar_one()
    rows = conn.execute(_records_query(conn, finding).limit(limit).offset(offset)).all()
    items = [
        {
            "row_num": r.row_num,
            "record_key": r.record_key,
            "group_no": r.group_no,
            "is_canonical": r.is_canonical,
            "cells": r.cells,
            "failing_columns": list(finding.columns),
        }
        for r in rows
    ]
    return items, total


def finding_records_csv(principal: Principal, conn: Connection, finding_id: UUID) -> str:
    """The same records as CSV for viewing, with formula-leading cells neutralised (NFR-004)."""
    require(principal, Permission.READ)
    finding = _finding_row(conn, finding_id)
    rows = conn.execute(_records_query(conn, finding)).all()
    columns: list[str] = []
    for row in rows:
        columns.extend(c for c in row.cells if c not in columns)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["row_num", "record_key", "group_no", "is_canonical", *columns])
    for row in rows:
        writer.writerow(
            [
                row.row_num,
                neutralise(row.record_key),
                "" if row.group_no is None else row.group_no,
                "" if row.is_canonical is None else str(row.is_canonical).lower(),
                *[neutralise(row.cells.get(c) or "") for c in columns],
            ]
        )
    return buffer.getvalue()
