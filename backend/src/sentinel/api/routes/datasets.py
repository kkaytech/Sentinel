"""Periods, ingestion and versions (Doc 4 §3.3)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Response, UploadFile
from sqlalchemy import Engine

from sentinel.api.deps import AuthContext, current_auth, get_engine, get_settings, protected
from sentinel.api.views import with_state
from sentinel.ingestion import service as ingestion
from sentinel.ingestion.service import Upload
from sentinel.shared.authz import Permission
from sentinel.shared.db import unit_of_work
from sentinel.shared.settings import Settings

router = APIRouter(prefix="/api/v1")


def _read(upload: UploadFile | None, limit: int) -> Upload | None:
    if upload is None:
        return None
    # One byte over the limit is enough to know the file is too large.
    return Upload(upload.filename or "upload.csv", upload.file.read(limit + 1))


@router.get("/datasets/{key}/periods", **protected(Permission.READ))
def get_periods(
    key: str,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        periods = ingestion.list_periods(ctx.principal, conn, key)
        items = []
        for period in periods:
            version = with_state(conn, period["current_version"])
            items.append(
                {
                    "period": period["period"],
                    "derived_state": version["derived_state"] if version else "NO_DATA",
                    "current_version": version,
                    "blocking_count": version["finding_counts"]["BLOCKING"] if version else 0,
                    "warning_count": version["finding_counts"]["WARNING"] if version else 0,
                }
            )
    return {"items": items, "total": len(items), "limit": len(items), "offset": 0}


@router.get("/datasets/{key}/periods/{period}", **protected(Permission.READ))
def get_period(
    key: str,
    period: str,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        detail = ingestion.get_period(ctx.principal, conn, key, period)
        detail["versions"] = [with_state(conn, v) for v in detail["versions"]]
    return detail


@router.post("/datasets/{key}/periods/{period}/ingestions", **protected(Permission.INGEST))
def post_ingestion(
    key: str,
    period: str,
    response: Response,
    suppliers: UploadFile | None = File(default=None),  # noqa: B008
    invoices: UploadFile | None = File(default=None),  # noqa: B008
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict[str, Any]:
    limit = settings.max_file_bytes
    files = {"suppliers": _read(suppliers, limit), "invoices": _read(invoices, limit)}
    result = ingestion.ingest(ctx.principal, engine, settings, key, period, files)
    response.status_code = 201 if result.created else 200
    with unit_of_work(engine) as conn:
        version = with_state(conn, result.version)
    return {"attempt": result.attempt, "version": version}


@router.get("/versions/{version_id}", **protected(Permission.READ))
def get_version(
    version_id: UUID,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        version = with_state(conn, ingestion.get_version(ctx.principal, conn, version_id))
    assert version is not None
    return version


@router.get("/versions/{version_id}/raw-files/{table}", **protected(Permission.DOWNLOAD_RAW))
def get_raw_file(
    version_id: UUID,
    table: str,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> Response:
    with unit_of_work(engine) as conn:
        raw = ingestion.get_raw_file(ctx.principal, conn, version_id, table)
    return Response(
        content=raw["bytes"],
        media_type="text/csv",
        headers={
            "X-Content-SHA256": raw["sha256"],
            "Content-Disposition": f'attachment; filename="{table}.csv"',
        },
    )
