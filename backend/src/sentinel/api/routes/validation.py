"""Validation runs, findings and impact (Doc 4 §3.4, §3.5)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import Engine

from sentinel.api.deps import AuthContext, current_auth, get_engine, get_settings, protected
from sentinel.impact import service as impact
from sentinel.shared.authz import Permission
from sentinel.shared.db import unit_of_work
from sentinel.shared.settings import Settings
from sentinel.validation import service as validation

router = APIRouter(prefix="/api/v1")
Severity = Literal["BLOCKING", "WARNING", "INFO"]


def _page(
    items: list[Any], total: int | None = None, limit: int | None = None, offset: int = 0
) -> dict[str, Any]:
    return {
        "items": items,
        "total": len(items) if total is None else total,
        "limit": len(items) if limit is None else limit,
        "offset": offset,
    }


@router.post("/versions/{version_id}/runs", status_code=202, **protected(Permission.RUN_VALIDATION))
def post_run(
    version_id: UUID,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict[str, Any]:
    """Start a run. Until the job queue arrives (M1 step 5) the run executes within the
    request, so the response already shows its final status."""
    with unit_of_work(engine) as conn:
        run_id = validation.start_run(ctx.principal, conn, version_id)
    validation.execute_run(
        engine, run_id, post_steps=[impact.compute], key_cap=settings.finding_key_cap
    )
    with unit_of_work(engine) as conn:
        return validation.get_run(ctx.principal, conn, run_id)


@router.get("/versions/{version_id}/runs", **protected(Permission.READ))
def get_runs(
    version_id: UUID,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return _page(validation.list_runs(ctx.principal, conn, version_id))


@router.get("/runs/{run_id}", **protected(Permission.READ))
def get_run(
    run_id: UUID,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return validation.get_run(ctx.principal, conn, run_id)


@router.get("/runs/{run_id}/findings", **protected(Permission.READ))
def get_findings(
    run_id: UUID,
    severity: Severity | None = None,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return _page(validation.list_findings(ctx.principal, conn, run_id, severity))


@router.get("/runs/{run_id}/impact", **protected(Permission.READ))
def get_run_impact(
    run_id: UUID,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return impact.run_impact(ctx.principal, conn, run_id)


@router.get("/findings/{finding_id}", **protected(Permission.READ))
def get_finding(
    finding_id: UUID,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return validation.get_finding(ctx.principal, conn, finding_id)


@router.get("/findings/{finding_id}/records", **protected(Permission.READ))
def get_finding_records(
    finding_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        items, total = validation.list_finding_records(
            ctx.principal, conn, finding_id, limit=limit, offset=offset
        )
    return _page(items, total, limit, offset)


@router.get("/findings/{finding_id}/records.csv", **protected(Permission.READ))
def get_finding_records_csv(
    finding_id: UUID,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> Response:
    with unit_of_work(engine) as conn:
        body = validation.finding_records_csv(ctx.principal, conn, finding_id)
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="finding-{finding_id}.csv"'},
    )


@router.get("/findings/{finding_id}/impact", **protected(Permission.READ))
def get_finding_impact(
    finding_id: UUID,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return impact.finding_impact(ctx.principal, conn, finding_id)
