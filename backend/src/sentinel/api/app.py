"""Application factory. Run with: uvicorn sentinel.api.app:create_app --factory"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from sqlalchemy import Engine

from sentinel import __version__
from sentinel.api.errors import install_error_handlers
from sentinel.api.routes import (
    audit,
    auth,
    config,
    datasets,
    health,
    review,
    users,
    validation,
)
from sentinel.config import service as config_service
from sentinel.review import service as review_service
from sentinel.shared import hooks
from sentinel.shared.context import set_correlation_id
from sentinel.shared.db import check_database_role, make_engine
from sentinel.shared.logging import configure_logging
from sentinel.shared.settings import Settings

log = logging.getLogger("sentinel.api")


def register_hooks() -> None:
    """Wire staleness propagation (FS §2.6) to the events that cause it. Idempotent."""
    hooks.register(hooks.VERSIONS_SUPERSEDED, review_service.on_versions_superseded)
    hooks.register(hooks.RUN_STARTED, review_service.on_run_started)
    hooks.register(hooks.RULE_SET_ACTIVATED, review_service.on_rule_set_activated)


SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    owns_engine = engine is None
    engine = engine or make_engine(settings.app_database_url)
    configure_logging()
    register_hooks()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        check_database_role(engine)  # refuse to start when over-privileged (ADR-018)
        config_service.load_at_startup(engine, Path(settings.config_dir))  # FR-002
        yield
        if owns_engine:
            engine.dispose()

    app = FastAPI(title="Sentinel", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    install_error_handlers(app)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = str(uuid.uuid4())
        set_correlation_id(correlation_id)
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response

    for router in (
        health.router,
        auth.router,
        users.router,
        audit.router,
        config.router,
        datasets.router,
        validation.router,
        review.router,
    ):
        app.include_router(router)
    return app
