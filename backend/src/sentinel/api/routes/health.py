"""Liveness/readiness endpoint (public)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from sentinel.api.deps import get_engine, public

router = APIRouter()


@router.get("/health", **public())
def health(engine: Engine = Depends(get_engine)) -> JSONResponse:  # noqa: B008
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "degraded", "db": "unavailable"})
    return JSONResponse(content={"status": "ok", "db": "ok"})
