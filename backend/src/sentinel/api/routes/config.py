"""Configuration endpoints (Doc 4 §3.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import Engine

from sentinel.api.deps import AuthContext, current_auth, get_engine, get_settings, protected
from sentinel.config import service as config_service
from sentinel.shared.authz import Permission
from sentinel.shared.db import unit_of_work
from sentinel.shared.errors import SentinelError
from sentinel.shared.settings import Settings

router = APIRouter(prefix="/api/v1")


@router.get("/datasets/{key}/config", **protected(Permission.READ))
def get_config(
    key: str,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return config_service.describe(ctx.principal, conn, key)


@router.post("/admin/config/reload", **protected(Permission.RELOAD_CONFIG))
def post_reload(
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> dict[str, Any]:
    try:
        with unit_of_work(engine) as conn:
            results = config_service.reload(ctx.principal, conn, Path(settings.config_dir))
    except SentinelError as exc:
        if exc.code == "CONFIG_INVALID":
            # The rejected reload changed nothing; record that it was attempted (FR-002.1).
            with unit_of_work(engine) as conn:
                config_service.record_rejection(conn, ctx.principal, len(exc.details["errors"]))
        raise
    first = results[0].as_dict()
    first["changed"] = any(r.changed for r in results)
    return first
