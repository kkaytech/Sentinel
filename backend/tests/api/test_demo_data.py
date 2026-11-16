"""The committed demo datasets behave as demo-data/README.md says."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sentinel.shared.authz import Role
from tests import reference
from tests.conftest import login

pytestmark = pytest.mark.db
DEMO = Path(__file__).resolve().parents[3] / "demo-data"


def _run(client: TestClient, headers: dict[str, str], period: str) -> dict[str, dict[str, Any]]:
    version = reference.upload(
        client,
        headers,
        suppliers=(DEMO / period / "suppliers.csv").read_bytes(),
        invoices=(DEMO / period / "invoices.csv").read_bytes(),
        period=period,
    )
    run = reference.completed(client, headers, version["id"])
    items = client.get(f"/api/v1/runs/{run['id']}/findings").json()["items"]
    return {f["rule_id"]: f for f in items}


def test_demo_datasets_are_consistent_with_their_periods(
    client: TestClient, make_user: Any
) -> None:
    make_user("demo_analyst", Role.ANALYST)
    headers = {"X-CSRF-Token": login(client, "demo_analyst")}

    assert _run(client, headers, "2026-11") == {}  # clean

    september = _run(client, headers, "2026-09")  # publishable after one waiver
    blocking = [f for f in september.values() if f["severity"] == "BLOCKING"]
    assert [f["rule_id"] for f in blocking] == ["INV_FK_SUPPLIER"] and blocking[0]["waivable"]
    # Invoices are dated inside September: only the planted rows fall outside the period.
    assert september["INV_OUT_OF_PERIOD"]["failing_count"] == 6
    assert "INV_FUTURE_DATED" not in september

    october = _run(client, headers, "2026-10")  # cannot be published
    assert october["INV_OUT_OF_PERIOD"]["failing_count"] == 7
    assert {"INV_PK_UNIQUE", "INV_TYPE_AMOUNTS"} <= {
        f["rule_id"] for f in october.values() if f["severity"] == "BLOCKING" and not f["waivable"]
    }
