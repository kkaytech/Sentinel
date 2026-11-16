"""The publication gate, snapshot, export and verification (PUB-001 to PUB-006, BR-002)."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg import errors
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from tests import reference
from tests.api.test_review import Actors, _approved_version, _issues, _validated, _waive
from tests.conftest import audit_events

pytestmark = pytest.mark.db
VERIFIER = Path(__file__).resolve().parents[3] / "scripts" / "verify_publication.py"


@pytest.fixture(scope="session")
def datasets(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("reference-publication")


@pytest.fixture
def actors(client: TestClient, make_user: Any) -> Actors:
    return Actors(client, make_user)


def _eligibility(actors: Actors, version_id: str) -> dict[str, str | None]:
    body = actors.analyst.get(f"/api/v1/versions/{version_id}/publication-eligibility").json()
    assert body["eligible"] == all(c["passed"] for c in body["checks"])
    return {c["id"]: c["code"] for c in body["checks"]}


def _publish(actors: Actors, version_id: str) -> Any:
    return actors.analyst.post(f"/api/v1/versions/{version_id}/publish", headers=actors.analyst_h)


def test_pub_001_every_failing_check_is_listed_and_publish_is_refused(
    actors: Actors, datasets: Path, owner_engine: Engine
) -> None:
    directory = reference.generate(datasets, "defective")
    version = reference.upload_dataset(actors.analyst, actors.analyst_h, directory)
    assert _eligibility(actors, version["id"]) == {
        "E1": None, "E2": None, "E3": None, "E4": "NO_CURRENT_VALIDATION",
        "E5": "UNRESOLVED_BLOCKING_ISSUES", "E6": "MISSING_APPROVAL", "E7": None,
    }  # fmt: skip
    reference.completed(actors.analyst, actors.analyst_h, version["id"])
    checks = _eligibility(actors, version["id"])
    assert checks["E4"] is None and checks["E5"] == "NON_WAIVABLE_BLOCKING_ISSUES"

    start = len(audit_events(owner_engine))
    response = _publish(actors, version["id"])
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "PUBLICATION_INELIGIBLE" and len(error["details"]["checks"]) == 7
    assert [e["event_type"] for e in audit_events(owner_engine)[start:]] == ["PUBLICATION_REFUSED"]
    with owner_engine.connect() as conn:
        assert conn.execute(
            text("SELECT outcome FROM app.publication_attempts")
        ).scalars().all() == ["FAILED"]
        assert conn.execute(text("SELECT count(*) FROM app.publications")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM published.invoices")).scalar_one() == 0
    # An ADMIN may run the dry run, and it reports that they cannot publish (E1).
    assert (
        actors.approver.post(
            f"/api/v1/versions/{version['id']}/publish", headers=actors.approver_h
        ).status_code
        == 409
    )


def test_pub_gate_needs_waiver_then_approval_then_publishes(
    actors: Actors, datasets: Path, owner_engine: Engine
) -> None:
    version, run = _validated(actors, datasets)
    assert _eligibility(actors, version["id"])["E5"] == "UNRESOLVED_BLOCKING_ISSUES"
    _waive(actors, _issues(actors, run["id"])["INV_FK_SUPPLIER"]["id"])
    checks = _eligibility(actors, version["id"])
    assert checks["E5"] is None and checks["E6"] == "MISSING_APPROVAL"
    assert _publish(actors, version["id"]).status_code == 409

    request = actors.analyst.post(
        f"/api/v1/versions/{version['id']}/review-requests",
        json={"note": "Ready"},
        headers=actors.analyst_h,
    ).json()
    actors.approver.post(
        f"/api/v1/review-requests/{request['id']}/decision",
        json={
            "decision": "APPROVE",
            "acknowledged_warning_count": run["finding_counts"]["WARNING"],
        },
        headers=actors.approver_h,
    )
    summary = actors.approver.get(f"/api/v1/versions/{version['id']}/review-summary").json()
    assert summary["eligibility"]["eligible"] is True

    published = _publish(actors, version["id"])
    assert published.status_code == 201, published.text
    ref = published.json()["publication_ref"]
    assert ref == "PUB-SUPINV-2026-10-001"
    state = actors.analyst.get(f"/api/v1/versions/{version['id']}").json()
    assert state["derived_state"] == "PUBLISHED" and state["publication_ref"] == ref

    # BR-002: one publication per period.
    assert _eligibility(actors, version["id"])["E7"] == "PERIOD_ALREADY_PUBLISHED"
    assert _publish(actors, version["id"]).status_code == 409

    detail = actors.analyst.get(f"/api/v1/publications/{ref}").json()
    assert detail["row_counts"] == {"invoices": 1986, "suppliers": 150}
    assert detail["manifest_sha256"] == published.json()["manifest_sha256"]
    assert actors.analyst.get("/api/v1/publications").json()["total"] == 1

    # PUB-005: the manifest is served as the exact stored bytes and records the evidence.
    raw = actors.analyst.get(f"/api/v1/publications/{ref}/manifest").content
    assert hashlib.sha256(raw).hexdigest() == detail["manifest_sha256"]
    manifest = json.loads(raw)
    assert manifest["manifest_format"] == "SENTINEL-MANIFEST-V1"
    assert manifest["review"]["decided_by"]["display_name"] == "Rv Approver"
    assert manifest["review"]["submitted_by"]["display_name"] == "Rv Analyst"
    assert [w["category"] for w in manifest["waivers"]] == ["KNOWN_SOURCE_LIMITATION"]
    assert manifest["policy"]["self_approval"] is False
    assert manifest["snapshot"]["snapshot_hash"] == detail["snapshot_hash"]
    assert all(isinstance(t["amount"], str) for t in manifest["impact_totals"])

    # PUB-006: the export is deterministic and verifies, online and offline.
    first = actors.approver.get(f"/api/v1/publications/{ref}/export").content
    assert first == actors.approver.get(f"/api/v1/publications/{ref}/export").content
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert archive.namelist() == [
            "manifest.json",
            "invoices.csv",
            "suppliers.csv",
            "README.txt",
        ]
        assert archive.read("manifest.json") == raw
        invoices = archive.read("invoices.csv")
        assert hashlib.sha256(invoices).hexdigest() == detail["table_hashes"]["invoices"]
        assert invoices.count(b"\n") == 1987
    verified = actors.analyst.post(
        f"/api/v1/publications/{ref}/verify", headers=actors.analyst_h
    ).json()
    assert (
        verified["result"] == "VERIFIED"
        and verified["snapshot_hash_ok"]
        and verified["manifest_sha256_ok"]
    )

    package = datasets / "export.zip"
    package.write_bytes(first)
    ok = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            str(package),
            "--expected-manifest-sha256",
            detail["manifest_sha256"],
        ],
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0 and "VERIFIED" in ok.stdout
    tampered = datasets / "tampered.zip"
    with zipfile.ZipFile(io.BytesIO(first)) as source, zipfile.ZipFile(tampered, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            target.writestr(
                name, data.replace(b"GBP", b"EUR", 1) if name == "invoices.csv" else data
            )
    bad = subprocess.run(
        [sys.executable, str(VERIFIER), str(tampered)], capture_output=True, text=True
    )
    assert bad.returncode == 1 and "FAILED" in bad.stdout

    types = [e["event_type"] for e in audit_events(owner_engine)]
    assert types.count("DATASET_PUBLISHED") == 1 and "PUBLICATION_VERIFIED" in types


def test_pub_003_stale_decisions_never_authorise_publication(
    actors: Actors, datasets: Path, owner_engine: Engine
) -> None:
    version, _ = _approved_version(actors, datasets)
    assert all(code is None for code in _eligibility(actors, version["id"]).values())
    rerun = reference.completed(actors.analyst, actors.analyst_h, version["id"])
    checks = _eligibility(actors, version["id"])
    assert checks["E5"] == "UNRESOLVED_BLOCKING_ISSUES" and checks["E6"] == "STALE_APPROVAL"

    # ADR-013: even if the stored statuses were wrong, the gate recomputes from the tuple.
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE app.waivers SET status = 'GRANTED', stale_reason = NULL"))
        conn.execute(
            text("UPDATE app.review_requests SET status = 'APPROVED', stale_reason = NULL")
        )
        conn.execute(
            text("UPDATE app.issues SET state = 'WAIVED' WHERE run_id = :r"), {"r": rerun["id"]}
        )
    checks = _eligibility(actors, version["id"])
    assert checks["E5"] == "UNRESOLVED_BLOCKING_ISSUES" and checks["E6"] == "STALE_APPROVAL"
    assert _publish(actors, version["id"]).status_code == 409


def test_pub_e2_e3_superseded_and_tampered_versions_are_refused(
    actors: Actors, datasets: Path, owner_engine: Engine
) -> None:
    version, _ = _approved_version(actors, datasets)
    with owner_engine.begin() as conn:  # only the owner can do this; the app role cannot
        conn.execute(
            text("UPDATE data.version_rows SET cells = cells || '{\"gross_amount\": \"1.00\"}'"
                 " WHERE table_name = 'invoices' AND row_num = 1")
        )  # fmt: skip
    assert _eligibility(actors, version["id"])["E3"] == "INTEGRITY_FAILURE"
    assert _publish(actors, version["id"]).status_code == 409
    reference.upload_dataset(
        actors.analyst, actors.analyst_h, reference.generate(datasets, "clean")
    )
    checks = _eligibility(actors, version["id"])
    assert checks["E2"] == "VERSION_SUPERSEDED"
    assert _publish(actors, version["id"]).status_code == 409


def test_published_data_is_immutable_and_the_database_backstop_holds(
    actors: Actors, datasets: Path, app_engine: Engine
) -> None:
    version, _ = _approved_version(actors, datasets)
    assert _publish(actors, version["id"]).status_code == 201
    for statement in (
        "UPDATE published.invoices SET gross_amount = 0",
        "DELETE FROM published.invoices",
        "TRUNCATE published.suppliers",
        "UPDATE app.publications SET snapshot_hash = repeat('0', 64)",
        "DELETE FROM app.publications",
        "INSERT INTO published.invoices (publication_id, invoice_id, currency, gross_amount)"
        " SELECT id, 'ROGUE', 'GBP', 1 FROM app.publications",
    ):
        with pytest.raises(DBAPIError) as exc, app_engine.begin() as conn:
            conn.execute(text(statement))
        assert isinstance(exc.value.orig, errors.InsufficientPrivilege), statement
    # A publication row cannot be inserted without a matching approval, whatever the code does.
    with pytest.raises(DBAPIError, match="publication refused"), app_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app.publications (id, publication_ref, dataset_period_id, dataset_key,"
                " period, dataset_version_id, content_hash, validation_run_id, rule_set_version_id,"
                " approval_decision_id, published_by, published_at, snapshot_format, snapshot_hash,"
                " table_hashes, row_counts, manifest_bytes, manifest_sha256)"
                " SELECT gen_random_uuid(), 'PUB-X', dataset_period_id, dataset_key, period,"
                " dataset_version_id, repeat('f', 64), validation_run_id, rule_set_version_id,"
                " approval_decision_id, published_by, now(), 'x', repeat('0', 64), '{}', '{}',"
                " ''::bytea, repeat('0', 64) FROM app.publications"
            )
        )
