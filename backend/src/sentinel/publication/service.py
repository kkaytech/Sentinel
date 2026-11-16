"""The publication gate (PUB-001 to PUB-006; FS §7, ARD §8.7).

`evaluate_eligibility` is the single function behind both the dry run and publish. It trusts
no stored status: it recomputes the content hash, the current run and the binding tuple, and
compares every waiver and approval with that tuple (ADR-013). Publish takes the period lock,
re-runs the function, and writes only if it passes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg import errors as pg_errors
from sqlalchemy import Connection, func, insert, literal, select
from sqlalchemy.exc import DBAPIError

from sentinel import __version__, audit
from sentinel.config import service as config_service
from sentinel.identity.tables import users
from sentinel.impact import service as impact
from sentinel.ingestion import service as ingestion
from sentinel.ingestion.tables import dataset_periods, dataset_versions
from sentinel.publication import canonical
from sentinel.publication.tables import PUBLISHED_TABLES, publication_attempts, publications
from sentinel.review.tables import (
    approval_decisions,
    issues,
    review_requests,
    waiver_decisions,
    waivers,
)
from sentinel.shared.authz import Permission, Principal, require
from sentinel.shared.errors import SentinelError, not_found
from sentinel.validation import service as validation
from sentinel.validation.rules import RunContext, cell, in_table, rows_alias, typed
from sentinel.validation.tables import findings, validation_runs

POLICY = {
    "required_approvals": 1,
    "self_approval": False,
    "warnings_block": False,
    "max_publications_per_period": 1,
}
TUPLE_COLUMNS = ("dataset_version_id", "content_hash", "validation_run_id", "rule_set_version_id")


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None


def _check(check_id: str, code: str | None = None, **details: Any) -> dict[str, Any]:
    return {"id": check_id, "passed": code is None, "code": code, "details": details}


def _same_tuple(row: Any, binding: dict[str, Any]) -> bool:
    return all(getattr(row, name) == binding[name] for name in TUPLE_COLUMNS)


def _version(conn: Connection, version_id: UUID, *, lock: bool = False) -> Any:
    query = (
        select(dataset_versions, dataset_periods.c.dataset_key, dataset_periods.c.period)
        .select_from(
            dataset_versions.join(
                dataset_periods, dataset_periods.c.id == dataset_versions.c.dataset_period_id
            )
        )
        .where(dataset_versions.c.id == version_id)
    )
    row = conn.execute(query).one_or_none()
    if row is None:
        raise SentinelError(404, "VERSION_NOT_FOUND", "Dataset version not found.")
    if lock:
        try:
            with conn.begin_nested():
                conn.execute(
                    select(dataset_periods.c.id)
                    .where(dataset_periods.c.id == row.dataset_period_id)
                    .with_for_update(nowait=True)
                )
        except DBAPIError as exc:
            if isinstance(exc.orig, pg_errors.LockNotAvailable):
                raise SentinelError(
                    409, "CONCURRENT_PUBLICATION",
                    "Another upload or publication for this period is in progress.",
                ) from exc  # fmt: skip
            raise
    return row


def _evaluate(conn: Connection, version: Any, principal: Principal) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    # E1 the caller may publish.
    checks.append(_check("E1", None if principal.has(Permission.PUBLISH) else "PERMISSION_DENIED"))
    # E2 the version is the period's active version.
    checks.append(_check("E2", None if version.status == "ACTIVE" else "VERSION_SUPERSEDED"))
    # E3 the stored content still hashes to the recorded value.
    intact = ingestion.recompute_content_hash(conn, version.id) == version.content_hash
    checks.append(_check("E3", None if intact else "INTEGRITY_FAILURE"))

    # E4 a current validation run exists (BR-003).
    active_rule_set = config_service.get_active(conn, version.dataset_key).rule_set_version_id
    runs = conn.execute(
        select(validation_runs)
        .where(validation_runs.c.dataset_version_id == version.id)
        .order_by(validation_runs.c.started_at.desc(), validation_runs.c.id.desc())
    ).all()
    latest = runs[0] if runs else None
    last = next((r for r in runs if r.status == "COMPLETED"), None)
    if latest is None or latest.status != "COMPLETED":
        state = latest.status if latest is not None else "NONE"
        checks.append(_check("E4", "NO_CURRENT_VALIDATION", latest_run_status=state))
    elif latest.rule_set_version_id != active_rule_set:
        checks.append(_check("E4", "STALE_VALIDATION"))
    else:
        checks.append(_check("E4", validation_run_id=str(latest.id)))

    binding = {
        "dataset_version_id": version.id,
        "content_hash": version.content_hash,
        "validation_run_id": last.id if last is not None else None,
        "rule_set_version_id": active_rule_set,
    }

    # E5 every BLOCKING finding of the last completed run is waivable and has a GRANTED
    # waiver bound to the current tuple. Issue states are not trusted.
    if last is None:
        checks.append(_check("E5", "UNRESOLVED_BLOCKING_ISSUES", reason="NO_COMPLETED_RUN"))
    else:
        blocking = conn.execute(
            select(findings.c.rule_id, findings.c.waivable, issues.c.id.label("issue_id"))
            .select_from(findings.outerjoin(issues, issues.c.finding_id == findings.c.id))
            .where(findings.c.run_id == last.id, findings.c.severity == "BLOCKING")
            .order_by(findings.c.rule_id)
        ).all()
        granted = conn.execute(
            select(waivers)
            .select_from(
                waivers.join(waiver_decisions, waiver_decisions.c.waiver_id == waivers.c.id)
            )
            .where(
                waivers.c.dataset_version_id == version.id,
                waiver_decisions.c.decision == "GRANT",
                waiver_decisions.c.decided_by != waivers.c.requested_by,
            )
        ).all()
        non_waivable = [b.rule_id for b in blocking if not b.waivable]
        unresolved = []
        for item in blocking:
            if not item.waivable:
                continue
            mine = [w for w in granted if w.issue_id == item.issue_id]
            if not any(_same_tuple(w, binding) for w in mine):
                unresolved.append(
                    {"rule_id": item.rule_id, "reason": "STALE_WAIVER" if mine else "NO_WAIVER"}
                )
        if non_waivable:
            checks.append(_check("E5", "NON_WAIVABLE_BLOCKING_ISSUES", rule_ids=non_waivable,
                                 unresolved=unresolved))  # fmt: skip
        elif unresolved:
            checks.append(_check("E5", "UNRESOLVED_BLOCKING_ISSUES", unresolved=unresolved))
        else:
            checks.append(_check("E5", blocking_count=len(blocking)))

    # E6 the latest approval is bound to the current tuple and was not a self-approval.
    approval = conn.execute(
        select(approval_decisions, review_requests.c.submitted_by)
        .select_from(
            approval_decisions.join(
                review_requests, review_requests.c.id == approval_decisions.c.review_request_id
            )
        )
        .where(
            approval_decisions.c.dataset_version_id == version.id,
            approval_decisions.c.decision == "APPROVE",
        )
        .order_by(approval_decisions.c.decided_at.desc(), approval_decisions.c.id.desc())
        .limit(1)
    ).one_or_none()
    approval_id = None
    if approval is None:
        checks.append(_check("E6", "MISSING_APPROVAL"))
    elif not _same_tuple(approval, binding):
        checks.append(_check("E6", "STALE_APPROVAL"))
    elif approval.decided_by == approval.submitted_by:
        checks.append(_check("E6", "SEGREGATION_OF_DUTIES"))
    else:
        approval_id = approval.id
        checks.append(_check("E6", approval_decision_id=str(approval.id)))

    # E7 one publication per period (BR-002).
    existing = conn.execute(
        select(publications.c.publication_ref).where(
            publications.c.dataset_period_id == version.dataset_period_id
        )
    ).scalar_one_or_none()
    if existing is None:
        checks.append(_check("E7"))
    else:
        checks.append(_check("E7", "PERIOD_ALREADY_PUBLISHED", publication_ref=existing))

    return {
        "eligible": all(c["passed"] for c in checks),
        "checks": checks,
        "_binding": binding,
        "_approval_id": approval_id,
        "_run": last,
    }


def _public(result: dict[str, Any]) -> dict[str, Any]:
    return {"eligible": result["eligible"], "checks": result["checks"]}


def evaluate_eligibility(
    principal: Principal, conn: Connection, version_id: UUID
) -> dict[str, Any]:
    """The dry run (PUB-002): every check, with every failure listed."""
    require(principal, Permission.DRY_RUN_PUBLICATION)
    return _public(_evaluate(conn, _version(conn, version_id), principal))


# ---- snapshot --------------------------------------------------------------------------------
def _typed_rows(ctx: RunContext, table: str) -> Any:
    """The version's rows for one table as typed values, in contract column order."""
    r = rows_alias()
    definition = ctx.contract.tables[table]
    columns = [
        (
            typed(cell(r, c.name), c.kind)
            if c.kind != "string"
            else func.nullif(cell(r, c.name), "")
        ).label(c.name)
        for c in definition.columns
    ]
    return select(*columns).where(in_table(r, ctx, table))


def _table_csv(conn: Connection, publication_id: UUID, table: str) -> tuple[bytes, int]:
    """Canonical CSV of a published table. Used at publish, export and verify alike."""
    target = PUBLISHED_TABLES[table]
    columns = [c for c in target.c if c.name != "publication_id"]
    key = next(c for c in columns if c.primary_key)
    rows = conn.execute(
        select(*columns).where(target.c.publication_id == publication_id).order_by(key.collate("C"))
    )
    return canonical.canonical_csv([c.name for c in columns], rows)


def _person(conn: Connection, user_id: UUID) -> dict[str, str]:
    name = conn.execute(select(users.c.display_name).where(users.c.id == user_id)).scalar_one()
    return {"id": str(user_id), "display_name": name}


def _manifest(
    principal: Principal, conn: Connection, version: Any, result: dict[str, Any],
    publication_ref: str, published_at: datetime, tables: dict[str, dict[str, Any]],
) -> dict[str, Any]:  # fmt: skip
    run = result["_run"]
    binding = result["_binding"]
    issue_rows = conn.execute(
        select(issues.c.id, issues.c.rule_id, issues.c.severity, issues.c.state)
        .where(issues.c.run_id == run.id)
        .order_by(issues.c.rule_id)
    ).all()
    waiver_rows = conn.execute(
        select(waivers, waiver_decisions.c.decided_by, waiver_decisions.c.decided_at,
               waiver_decisions.c.comment)
        .select_from(waivers.join(waiver_decisions, waiver_decisions.c.waiver_id == waivers.c.id))
        .where(waivers.c.validation_run_id == run.id, waiver_decisions.c.decision == "GRANT")
        .order_by(waivers.c.requested_at, waivers.c.id)
    ).all()  # fmt: skip
    approval = conn.execute(
        select(approval_decisions, review_requests.c.submitted_by, review_requests.c.submitted_at,
               review_requests.c.note)
        .select_from(
            approval_decisions.join(
                review_requests, review_requests.c.id == approval_decisions.c.review_request_id
            )
        )
        .where(approval_decisions.c.id == result["_approval_id"])
    ).one()  # fmt: skip
    run_impact = impact.run_impact(principal, conn, run.id)
    return {
        "manifest_format": canonical.MANIFEST_FORMAT,
        "publication_ref": publication_ref,
        "dataset": {"key": version.dataset_key, "period": version.period},
        "version": {
            "id": str(version.id),
            "label": version.label,
            "content_hash": version.content_hash,
            "content_hash_algorithm": version.hash_algorithm,
        },
        "contract_version_id": str(version.contract_version_id),
        "rule_set_version_id": str(binding["rule_set_version_id"]),
        "validation_run": {
            "id": str(run.id),
            "engine_version": run.engine_version,
            "reference_date": run.reference_date.isoformat(),
            "finding_counts": run.finding_counts,
        },
        "issues": [
            {"id": str(i.id), "rule_id": i.rule_id, "severity": i.severity, "final_state": i.state}
            for i in issue_rows
        ],
        "waivers": [
            {
                "issue_id": str(w.issue_id),
                "category": w.category,
                "justification": w.justification,
                "requested_by": _person(conn, w.requested_by),
                "requested_at": _iso(w.requested_at),
                "decided_by": _person(conn, w.decided_by),
                "decided_at": _iso(w.decided_at),
                "comment": w.comment,
            }
            for w in waiver_rows
        ],
        "review": {
            "request_id": str(approval.review_request_id),
            "submitted_by": _person(conn, approval.submitted_by),
            "submitted_at": _iso(approval.submitted_at),
            "note": approval.note,
            "decision": approval.decision,
            "decided_by": _person(conn, approval.decided_by),
            "decided_at": _iso(approval.decided_at),
            "comment": approval.comment,
            "acknowledged_warning_count": approval.acknowledged_warning_count,
        },
        "policy": POLICY,
        "impact_totals": [
            {k: t[k] for k in ("category", "currency", "amount", "record_count")}
            for t in run_impact["totals"]
        ],
        "kpis": [
            {k: v[k] for k in ("kpi_id", "currency", "as_reported", "fully_adjusted", "direction")}
            for v in run_impact["kpis"]
        ],
        "snapshot": {
            "format": canonical.SNAPSHOT_FORMAT,
            "tables": [
                {"name": name, "rows": tables[name]["rows"], "sha256": tables[name]["sha256"]}
                for name in sorted(tables)
            ],
            "snapshot_hash": canonical.snapshot_hash({n: t["sha256"] for n, t in tables.items()}),
        },
        "published_by": {"id": str(principal.user_id), "display_name": principal.display_name},
        "published_at": _iso(published_at),
        "engine_version": __version__,
        "advisory": {"ai_explanation_ids": []},
    }


def publish(principal: Principal, conn: Connection, version_id: UUID) -> dict[str, Any]:
    """Publish a version, or record why it was refused. Returns {published, ...}.

    The caller commits in both cases, so a refusal keeps its attempt record and audit event,
    and then turns `published: False` into the 409 response.
    """
    require(principal, Permission.PUBLISH)
    version = _version(conn, version_id, lock=True)
    result = _evaluate(conn, version, principal)
    if not result["eligible"]:
        failed = [c["code"] for c in result["checks"] if not c["passed"]]
        conn.execute(
            insert(publication_attempts).values(
                dataset_version_id=version_id,
                attempted_by=principal.user_id,
                outcome="FAILED",
                checks=result["checks"],
            )
        )
        audit.record(
            conn,
            actor=principal,
            event_type="PUBLICATION_REFUSED",
            entity_type="dataset_version",
            entity_id=str(version_id),
            dataset_version_id=version_id,
            payload={"failed": failed},
        )
        return {"published": False, **_public(result)}

    run = result["_run"]
    start, end = validation.period_bounds(version.period)
    ctx = RunContext(
        version_id=version.id,
        contract=config_service.get_contract(conn, version.contract_version_id),
        period_start=start,
        period_end=end,
        reference_date=run.reference_date,
    )
    publication_id = uuid4()
    publication_ref = f"PUB-{version.dataset_key}-{version.period}-001"
    published_at = datetime.now(UTC).replace(microsecond=0)

    # 1. Hash the typed rows before the publication row exists, because that row is
    #    insert-only and must already carry the hashes and the manifest.
    expected: dict[str, dict[str, Any]] = {}
    for table, target in PUBLISHED_TABLES.items():
        typed_rows = _typed_rows(ctx, table).subquery("t")
        key = next(c.name for c in target.c if c.primary_key and c.name != "publication_id")
        rows = conn.execute(select(typed_rows).order_by(typed_rows.c[key].collate("C")))
        data, count = canonical.canonical_csv([c.name for c in typed_rows.c], rows)
        expected[table] = {"rows": count, "sha256": canonical.sha256(data)}
    manifest = _manifest(principal, conn, version, result, publication_ref, published_at, expected)
    manifest_data = canonical.manifest_bytes(manifest)

    conn.execute(
        insert(publications).values(
            id=publication_id,
            publication_ref=publication_ref,
            dataset_period_id=version.dataset_period_id,
            dataset_key=version.dataset_key,
            period=version.period,
            approval_decision_id=result["_approval_id"],
            published_by=principal.user_id,
            published_at=published_at,
            snapshot_format=canonical.SNAPSHOT_FORMAT,
            snapshot_hash=manifest["snapshot"]["snapshot_hash"],
            table_hashes={name: t["sha256"] for name, t in expected.items()},
            row_counts={name: t["rows"] for name, t in expected.items()},
            manifest_bytes=manifest_data,
            manifest_sha256=canonical.sha256(manifest_data),
            **result["_binding"],
        )
    )
    # 2. Write the snapshot. The seal guard ties every row to this transaction.
    for table, target in PUBLISHED_TABLES.items():
        typed_rows = _typed_rows(ctx, table).subquery("t")
        names = [c.name for c in typed_rows.c]
        conn.execute(
            insert(target).from_select(
                ["publication_id", *names],
                select(literal(publication_id), *typed_rows.c),
            )
        )
        # 3. What was stored must reproduce the hash that the manifest promises.
        data, count = _table_csv(conn, publication_id, table)
        if canonical.sha256(data) != expected[table]["sha256"] or count != expected[table]["rows"]:
            raise RuntimeError(f"published snapshot of {table} does not match its manifest")

    conn.execute(
        insert(publication_attempts).values(
            dataset_version_id=version_id,
            attempted_by=principal.user_id,
            outcome="SUCCEEDED",
            checks=result["checks"],
            publication_id=publication_id,
        )
    )
    audit.record(
        conn,
        actor=principal,
        event_type="DATASET_PUBLISHED",
        entity_type="publication",
        entity_id=publication_ref,
        dataset_version_id=version_id,
        payload={
            "snapshot_hash": manifest["snapshot"]["snapshot_hash"],
            "manifest_sha256": canonical.sha256(manifest_data),
            "row_counts": {name: t["rows"] for name, t in expected.items()},
        },
    )
    return {
        "published": True,
        "publication_ref": publication_ref,
        "snapshot_hash": manifest["snapshot"]["snapshot_hash"],
        "manifest_sha256": canonical.sha256(manifest_data),
    }


# ---- queries ---------------------------------------------------------------------------------
def _publication_view(conn: Connection, row: Any) -> dict[str, Any]:
    label = conn.execute(
        select(dataset_versions.c.label).where(dataset_versions.c.id == row.dataset_version_id)
    ).scalar_one()
    return {
        "publication_ref": row.publication_ref,
        "dataset": row.dataset_key,
        "period": row.period,
        "version_id": str(row.dataset_version_id),
        "version_label": label,
        "status": row.status,
        "published_by": _person(conn, row.published_by),
        "published_at": _iso(row.published_at),
        "snapshot_format": row.snapshot_format,
        "snapshot_hash": row.snapshot_hash,
        "table_hashes": row.table_hashes,
        "row_counts": row.row_counts,
        "manifest_sha256": row.manifest_sha256,
    }


def _publication(conn: Connection, publication_ref: str) -> Any:
    row = conn.execute(
        select(publications).where(publications.c.publication_ref == publication_ref)
    ).one_or_none()
    if row is None:
        raise not_found("Publication")
    return row


def list_publications(principal: Principal, conn: Connection) -> list[dict[str, Any]]:
    require(principal, Permission.READ)
    rows = conn.execute(
        select(publications).order_by(
            publications.c.published_at.desc(), publications.c.publication_ref
        )
    ).all()
    return [_publication_view(conn, r) for r in rows]


def get_publication(principal: Principal, conn: Connection, publication_ref: str) -> dict[str, Any]:
    require(principal, Permission.READ)
    return _publication_view(conn, _publication(conn, publication_ref))


def publication_for_version(conn: Connection, version_id: UUID) -> str | None:
    ref: str | None = conn.execute(
        select(publications.c.publication_ref).where(
            publications.c.dataset_version_id == version_id
        )
    ).scalar_one_or_none()
    return ref


def get_manifest(principal: Principal, conn: Connection, publication_ref: str) -> bytes:
    """The exact stored manifest bytes (PUB-005)."""
    require(principal, Permission.READ)
    return bytes(_publication(conn, publication_ref).manifest_bytes)


def export(principal: Principal, conn: Connection, publication_ref: str) -> bytes:
    """The verification package, regenerated from the immutable snapshot (PUB-006)."""
    require(principal, Permission.EXPORT_PUBLICATION)
    row = _publication(conn, publication_ref)
    tables = {name: _table_csv(conn, row.id, name)[0] for name in PUBLISHED_TABLES}
    return canonical.export_zip(bytes(row.manifest_bytes), tables)


def verify(principal: Principal, conn: Connection, publication_ref: str) -> dict[str, Any]:
    """Recompute every hash from the stored snapshot and compare with the record."""
    require(principal, Permission.READ)
    row = _publication(conn, publication_ref)
    tables = []
    actual_hashes = {}
    for name in sorted(PUBLISHED_TABLES):
        data, count = _table_csv(conn, row.id, name)
        actual_hashes[name] = canonical.sha256(data)
        tables.append(
            {
                "table": name,
                "expected_sha256": row.table_hashes.get(name),
                "actual_sha256": actual_hashes[name],
                "rows_expected": row.row_counts.get(name),
                "rows_actual": count,
            }
        )
    snapshot_ok = canonical.snapshot_hash(actual_hashes) == row.snapshot_hash
    manifest_ok = canonical.sha256(bytes(row.manifest_bytes)) == row.manifest_sha256
    tables_ok = all(
        t["expected_sha256"] == t["actual_sha256"] and t["rows_expected"] == t["rows_actual"]
        for t in tables
    )
    verified = tables_ok and snapshot_ok and manifest_ok
    audit.record(
        conn,
        actor=principal,
        event_type="PUBLICATION_VERIFIED" if verified else "PUBLICATION_VERIFICATION_FAILED",
        entity_type="publication",
        entity_id=publication_ref,
        dataset_version_id=row.dataset_version_id,
    )
    return {
        "result": "VERIFIED" if verified else "FAILED",
        "tables": tables,
        "snapshot_hash_ok": snapshot_ok,
        "manifest_sha256_ok": manifest_ok,
    }
