"""Publication eligibility, publish, export and verification (Doc 4 §3.8)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import Engine

from sentinel.api.deps import AuthContext, current_auth, get_engine, protected
from sentinel.publication import service as publication
from sentinel.shared.authz import Permission
from sentinel.shared.db import unit_of_work
from sentinel.shared.errors import SentinelError

router = APIRouter(prefix="/api/v1")


@router.get(
    "/versions/{version_id}/publication-eligibility", **protected(Permission.DRY_RUN_PUBLICATION)
)
def get_eligibility(
    version_id: UUID,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return publication.evaluate_eligibility(ctx.principal, conn, version_id)


@router.post("/versions/{version_id}/publish", status_code=201, **protected(Permission.PUBLISH))
def post_publish(
    version_id: UUID,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    # The transaction commits either way: a refusal keeps its attempt record and audit event.
    with unit_of_work(engine) as conn:
        result = publication.publish(ctx.principal, conn, version_id)
    if not result.pop("published"):
        failed = sum(1 for c in result["checks"] if not c["passed"])
        raise SentinelError(
            409, "PUBLICATION_INELIGIBLE", f"Publication refused: {failed} check(s) failed.", result
        )
    return result


@router.get("/publications", **protected(Permission.READ))
def get_publications(
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        items = publication.list_publications(ctx.principal, conn)
    return {"items": items, "total": len(items), "limit": len(items), "offset": 0}


@router.get("/publications/{publication_ref}", **protected(Permission.READ))
def get_publication(
    publication_ref: str,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return publication.get_publication(ctx.principal, conn, publication_ref)


@router.get("/publications/{publication_ref}/manifest", **protected(Permission.READ))
def get_manifest(
    publication_ref: str,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> Response:
    with unit_of_work(engine) as conn:
        body = publication.get_manifest(ctx.principal, conn, publication_ref)
    return Response(content=body, media_type="application/json")


@router.get("/publications/{publication_ref}/export", **protected(Permission.EXPORT_PUBLICATION))
def get_export(
    publication_ref: str,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> Response:
    with unit_of_work(engine) as conn:
        body = publication.export(ctx.principal, conn, publication_ref)
    return Response(
        content=body,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{publication_ref}.zip"'},
    )


@router.post("/publications/{publication_ref}/verify", **protected(Permission.READ))
def post_verify(
    publication_ref: str,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return publication.verify(ctx.principal, conn, publication_ref)
