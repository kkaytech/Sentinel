"""The application serves the built frontend and falls back to index.html for deep links."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from sentinel.api.app import create_app
from sentinel.shared.settings import Settings

pytestmark = pytest.mark.db


@pytest.fixture
def spa(tmp_path: Path, settings: Settings, app_engine: Engine) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Sentinel</title><div id=root></div>")
    (dist / "assets" / "app-abc123.js").write_text("console.log('sentinel')")
    return TestClient(create_app(replace(settings, frontend_dir=str(dist)), engine=app_engine))


def test_index_assets_and_deep_links_are_served(spa: TestClient) -> None:
    with spa:
        root = spa.get("/")
        assert root.status_code == 200 and "<title>Sentinel</title>" in root.text
        assert root.headers["cache-control"] == "no-cache"
        assert "default-src 'self'" in root.headers["content-security-policy"]
        asset = spa.get("/assets/app-abc123.js")
        assert asset.status_code == 200 and "javascript" in asset.headers["content-type"]
        for path in ("/periods", "/versions/123/review", "/publications/PUB-SUPINV-2026-09-001"):
            deep = spa.get(path)
            assert deep.status_code == 200 and "<title>Sentinel</title>" in deep.text, path


def test_api_routes_keep_precedence_over_the_frontend(spa: TestClient) -> None:
    with spa:
        assert spa.get("/health").json()["status"] == "ok"
        assert spa.get("/api/v1/session").status_code == 401
        missing = spa.get("/api/v1/no-such-endpoint")
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"
        assert spa.get("/assets/missing.js").status_code == 200  # falls back to the app shell


def test_without_a_build_the_api_runs_alone(client: TestClient) -> None:
    assert client.get("/").status_code == 404
    assert client.get("/health").status_code == 200
