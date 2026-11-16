"""Serve the built single-page frontend from the application (one deployable unit).

Mounted last, so API routes always win. Any other GET falls back to index.html, which lets
the browser router handle deep links such as /versions/<id>/review. Unknown /api paths still
return the JSON 404 envelope. In development the Vite server does this job instead.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

NOT_FRONTEND = ("api/", "health", "docs", "redoc", "openapi.json")


class SinglePageApp(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or path.startswith(NOT_FRONTEND):
                raise
            response = await super().get_response("index.html", scope)
        if path in ("", ".", "index.html") or response.headers.get("content-type", "").startswith(
            "text/html"
        ):
            # The entry page must always be fresh; hashed assets may be cached.
            response.headers["Cache-Control"] = "no-cache"
        return response


def mount_frontend(app: FastAPI, directory: str | None) -> bool:
    if not directory or not (Path(directory) / "index.html").is_file():
        return False
    app.mount("/", SinglePageApp(directory=directory, html=True), name="frontend")
    return True
