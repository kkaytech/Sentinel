"""Configuration versioning and reload (FR-002)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from psycopg import errors
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from sentinel.shared.authz import Role
from tests.conftest import audit_events, login

pytestmark = pytest.mark.db
RELOAD = "/api/v1/admin/config/reload"
RULES = Path("datasets") / "supplier_invoices" / "rules.yaml"


def _edit_rules(config_dir: Path, mutate: Any) -> None:
    path = config_dir / RULES
    rules = yaml.safe_load(path.read_text())
    mutate(rules)
    path.write_text(yaml.safe_dump(rules))


def _versions(owner_engine: Engine) -> list[tuple[str, str]]:
    with owner_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT kind, content_sha256 FROM app.config_versions ORDER BY 1, 2")
        )
        return [(r.kind, r.content_sha256) for r in rows]


def _admin(client: TestClient, make_user: Any) -> dict[str, str]:
    make_user("admin_cfg", Role.ADMIN)
    return {"X-CSRF-Token": login(client, "admin_cfg")}


def test_fr_002_startup_activates_the_files_as_a_system_event(
    client: TestClient, make_user: Any, owner_engine: Engine
) -> None:
    activated = [e for e in audit_events(owner_engine) if e["event_type"] == "CONFIG_ACTIVATED"]
    assert len(activated) == 1 and activated[0]["actor_kind"] == "SYSTEM"
    assert activated[0]["payload"]["changed"] == ["CONTRACT", "RULE_SET"]
    make_user("reader", Role.APPROVER)
    login(client, "reader")
    body = client.get("/api/v1/datasets/SUPINV/config").json()
    assert len(body["rules"]) == 32
    assert [r["id"] for r in body["rules"]] == sorted(r["id"] for r in body["rules"])
    assert client.get("/api/v1/datasets/NOPE/config").status_code == 404


def test_fr_002_2_reloading_unchanged_files_creates_no_version(
    client: TestClient, make_user: Any, owner_engine: Engine
) -> None:
    headers = _admin(client, make_user)
    before = _versions(owner_engine)
    start = len(audit_events(owner_engine))
    response = client.post(RELOAD, headers=headers)
    assert response.status_code == 200 and response.json()["changed"] is False
    assert _versions(owner_engine) == before
    assert [e["event_type"] for e in audit_events(owner_engine)[start:]] == [
        "CONFIG_RELOAD_UNCHANGED"
    ]


def test_fr_002_3_changed_severity_creates_a_new_rule_set_version(
    client: TestClient, make_user: Any, owner_engine: Engine, config_dir: Path
) -> None:
    headers = _admin(client, make_user)
    first = client.post(RELOAD, headers=headers).json()
    start = len(audit_events(owner_engine))
    _edit_rules(config_dir, lambda r: r["rules"][-1].update(severity="INFO"))
    second = client.post(RELOAD, headers=headers).json()
    assert second["changed"] is True
    assert second["rule_set_version_id"] != first["rule_set_version_id"]
    assert second["contract_version_id"] == first["contract_version_id"]
    hashes = [h for kind, h in _versions(owner_engine) if kind == "RULE_SET"]
    assert len(hashes) == 2 and hashes[0] != hashes[1]
    events = audit_events(owner_engine)[start:]
    assert [e["event_type"] for e in events] == ["CONFIG_ACTIVATED"]
    assert events[0]["payload"]["changed"] == ["RULE_SET"] and events[0]["actor_kind"] == "USER"

    # Reverting the content still creates a new version, so old binding tuples stay stale.
    _edit_rules(config_dir, lambda r: r["rules"][-1].update(severity="WARNING"))
    third = client.post(RELOAD, headers=headers).json()
    assert third["rule_set_version_id"] not in (
        first["rule_set_version_id"],
        second["rule_set_version_id"],
    )
    assert len([h for kind, h in _versions(owner_engine) if kind == "RULE_SET"]) == 3


def test_fr_002_1_invalid_configuration_keeps_the_active_version(
    client: TestClient, make_user: Any, owner_engine: Engine, config_dir: Path
) -> None:
    headers = _admin(client, make_user)
    active = client.post(RELOAD, headers=headers).json()
    before = _versions(owner_engine)
    start = len(audit_events(owner_engine))
    _edit_rules(config_dir, lambda r: r["rules"][0].update(type="made_up"))
    response = client.post(RELOAD, headers=headers)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "CONFIG_INVALID"
    assert any("INV_SCHEMA_REQUIRED" in e and "made_up" in e for e in error["details"]["errors"])
    assert _versions(owner_engine) == before
    assert [e["event_type"] for e in audit_events(owner_engine)[start:]] == ["CONFIG_REJECTED"]

    (config_dir / RULES).write_text("rules: [unterminated")
    assert client.post(RELOAD, headers=headers).status_code == 422
    body = client.get("/api/v1/datasets/SUPINV/config").json()
    assert body["rule_set_version"]["id"] == active["rule_set_version_id"]


def test_reload_requires_admin(client: TestClient, make_user: Any) -> None:
    make_user("analyst_cfg", Role.ANALYST)
    csrf = login(client, "analyst_cfg")
    response = client.post(RELOAD, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 403


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE app.config_versions SET canonical_json = '{}'",
        "DELETE FROM app.config_versions",
        "DELETE FROM app.active_config",
        "UPDATE app.active_config SET dataset_key = 'OTHER'",
    ],
)
def test_fr_002_config_versions_are_immutable_for_the_app_role(
    client: TestClient, app_engine: Engine, statement: str
) -> None:
    with pytest.raises(DBAPIError) as exc, app_engine.begin() as conn:
        conn.execute(text(statement))
    assert isinstance(exc.value.orig, errors.InsufficientPrivilege)
