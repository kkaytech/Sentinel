"""Error envelope (Doc 4 §2.3). Never leaks SQL, stack traces, inputs or cell values."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from sentinel.shared.context import current_correlation_id
from sentinel.shared.errors import SentinelError

log = logging.getLogger("sentinel.api")


def envelope(
    status: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "correlation_id": current_correlation_id(),
            }
        },
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SentinelError)
    async def _sentinel(_: Request, exc: SentinelError) -> JSONResponse:
        return envelope(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Strip `input` and `ctx`: they can echo submitted values such as passwords.
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return envelope(422, "VALIDATION_ERROR", "Request validation failed.", {"errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return envelope(exc.status_code, code, "Not found." if exc.status_code == 404 else code)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_exception", extra={"exc_type": type(exc).__name__})
        return envelope(500, "INTERNAL_ERROR", "An unexpected error occurred.")
