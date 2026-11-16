"""Ingestion and immutable versions over the API (FR-003, FR-004)."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg import errors
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from sentinel.ingestion.service import recompute_content_hash, validate_period
from sentinel.shared.authz import Role
from sentinel.shared.errors import SentinelError
from tests.conftest import audit_events, login

pytestmark = pytest.mark.db
PERIOD = "2026-10"
URL = f"/api/v1/datasets/SUPINV/periods/{PERIOD}/ingestions"
SUPPLIERS = (
    b"supplier_id,supplier_name,country_code,default_currency,status,active_from,active_to,tax_id\n"
    b"S1,Acme Ltd,GB,GBP,ACTIVE,2020-01-01,,\n"
)
INVOICES = (
    b"invoice_id,supplier_id,supplier_invoice_number,document_type,invoice_date,due_date,"
    b"currency,net_amount,tax_amount,gross_amount,status,description\n"
    b"I1,S1,A-1,INVOICE,2026-10-02,2026-11-01,GBP,100.00,20.00,120.00,PAID,first\n"
    b'I2,S1,A-2,INVOICE,2026-10-03,2026-11-02,GBP,10.00,2.00,"12,50O.00",PAID,"=cmd, x"\n'
)


def _files(
    suppliers: bytes | None = SUPPLIERS, invoices: bytes | None = INVOICES
) -> dict[str, Any]:
    files = {}
    if suppliers is not None:
        files["suppliers"] = ("suppliers.csv", suppliers, "text/csv")
    if invoices is not None:
        files["invoices"] = ("../../etc/invoices.csv", invoices, "text/csv")
    return files


@pytest.fixture
def analyst(client: TestClient, make_user: Any) -> dict[str, str]:
    make_user("analyst_ing", Role.ANALYST)
    return {"X-CSRF-Token": login(client, "analyst_ing")}


def _count(owner_engine: Engine, table: str) -> int:
    with owner_engine.connect() as conn:
        return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def _attempts(owner_engine: Engine) -> list[Any]:
    with owner_engine.connect() as conn:
        return list(conn.execute(text("SELECT * FROM app.ingestion_attempts ORDER BY started_at")))


def test_fr_003_1_valid_files_create_exactly_one_version(
    client: TestClient, analyst: dict[str, str], owner_engine: Engine, app_engine: Engine
) -> None:
    start = len(audit_events(owner_engine))
    response = client.post(URL, files=_files(), headers=analyst)
    assert response.status_code == 201, response.text
    version = response.json()["version"]
    assert version["label"] == "SUPINV-2026-10-v1" and version["seq"] == 1
    assert version["status"] == "ACTIVE" and version["derived_state"] == "INGESTED"
    assert version["hash_algorithm"] == "SENTINEL-CONTENT-V1"
    assert version["row_counts"] == {"invoices": 2, "suppliers": 1}
    assert _count(owner_engine, "app.dataset_versions") == 1
    assert _count(owner_engine, "data.version_rows") == 3
    events = audit_events(owner_engine)[start:]
    assert [e["event_type"] for e in events] == ["VERSION_CREATED"]
    assert "12,50O.00" not in str(events[0]["payload"])  # no cell values in audit payloads

    attempt = response.json()["attempt"]
    assert attempt["status"] == "SUCCEEDED" and attempt["dataset_version_id"] == version["id"]
    files = {f["table"]: f for f in attempt["files"]}
    assert files["invoices"]["sha256"] == hashlib.sha256(INVOICES).hexdigest()
    assert files["invoices"]["filename"] == "invoices.csv"  # path components are dropped
    assert files["invoices"]["rows"] == 2

    # FR-003.4: the unparseable amount is stored as raw text. FR-004.1: the hash is reproducible.
    with app_engine.connect() as conn:
        cell = conn.execute(
            text("SELECT cells ->> 'gross_amount' FROM data.version_rows "
                 "WHERE table_name = 'invoices' AND row_num = 2")
        ).scalar_one()  # fmt: skip
        assert cell == "12,50O.00"
        assert recompute_content_hash(conn, version["id"]) == version["content_hash"]

    listing = client.get("/api/v1/datasets/SUPINV/periods").json()["items"]
    assert [(p["period"], p["derived_state"]) for p in listing] == [(PERIOD, "INGESTED")]
    assert client.get(f"/api/v1/versions/{version['id']}").json()["label"] == version["label"]


def test_fr_004_4_raw_files_download_byte_identical(
    client: TestClient, analyst: dict[str, str]
) -> None:
    version = client.post(URL, files=_files(), headers=analyst).json()["version"]
    response = client.get(f"/api/v1/versions/{version['id']}/raw-files/invoices")
    assert response.status_code == 200 and response.content == INVOICES
    assert response.headers["X-Content-SHA256"] == hashlib.sha256(INVOICES).hexdigest()
    assert client.get(f"/api/v1/versions/{version['id']}/raw-files/nope").status_code == 404


def test_fr_003_2_missing_table_file_is_rejected_naming_the_table(
    client: TestClient, analyst: dict[str, str], owner_engine: Engine
) -> None:
    start = len(audit_events(owner_engine))
    response = client.post(URL, files=_files(invoices=None), headers=analyst)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "MISSING_TABLE_FILE" and "invoices" in error["message"]
    assert _count(owner_engine, "app.dataset_versions") == 0
    assert _attempts(owner_engine) == []  # malformed requests create no attempt (FS §3)
    assert [e["event_type"] for e in audit_events(owner_engine)[start:]] == ["INGESTION_REJECTED"]


def test_fr_003_3_ragged_row_is_rejected_with_line_numbers(
    client: TestClient, analyst: dict[str, str], owner_engine: Engine
) -> None:
    bad = INVOICES + b"I3,S1\n"
    response = client.post(URL, files=_files(invoices=bad), headers=analyst)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INGESTION_STRUCTURAL_ERROR"
    assert error["details"]["errors"] == [{"table": "invoices", "line": 4, "code": "RAGGED_ROW"}]
    assert error["details"]["total"] == 1
    assert _count(owner_engine, "app.dataset_versions") == 0
    assert _count(owner_engine, "data.version_rows") == 0
    (attempt,) = _attempts(owner_engine)
    assert attempt.status == "FAILED" and attempt.errors["total"] == 1
    period = client.get(f"/api/v1/datasets/SUPINV/periods/{PERIOD}").json()
    assert period["versions"] == [] and period["ingestion_attempts"][0]["status"] == "FAILED"
    listing = client.get("/api/v1/datasets/SUPINV/periods").json()["items"]
    assert listing[0]["derived_state"] == "NO_DATA"


def test_fr_003_5_size_and_row_limits_state_the_limit(
    client: TestClient, analyst: dict[str, str], owner_engine: Engine
) -> None:
    client.app.state.settings = type(client.app.state.settings)(  # type: ignore[attr-defined]
        **{**client.app.state.settings.__dict__, "max_rows": 1}  # type: ignore[attr-defined]
    )
    response = client.post(URL, files=_files(), headers=analyst)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["details"]["errors"][0]["code"] == "ROW_LIMIT_EXCEEDED"
    assert "1 rows" in error["message"]

    client.app.state.settings = type(client.app.state.settings)(  # type: ignore[attr-defined]
        **{**client.app.state.settings.__dict__, "max_file_bytes": 1024 * 1024}  # type: ignore[attr-defined]
    )
    big = INVOICES + b" " * (1024 * 1024)
    response = client.post(URL, files=_files(invoices=big), headers=analyst)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert "1 MB" in response.json()["error"]["message"]
    assert _count(owner_engine, "app.dataset_versions") == 0


def test_fr_003_6_fault_before_commit_leaves_no_version_data(
    client: TestClient,
    analyst: dict[str, str],
    owner_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentinel.ingestion import service

    real = service._copy_rows
    calls: list[str] = []

    def failing(conn: Any, version_id: Any, table: Any) -> None:
        calls.append(table.name)
        if len(calls) == 2:
            raise RuntimeError("disk full")
        real(conn, version_id, table)

    monkeypatch.setattr(service, "_copy_rows", failing)
    no_raise = TestClient(client.app, raise_server_exceptions=False)
    no_raise.cookies = client.cookies
    response = no_raise.post(URL, files=_files(), headers=analyst)
    assert response.status_code == 500 and calls == ["invoices", "suppliers"]
    for table in ("app.dataset_versions", "data.version_rows", "data.raw_files"):
        assert _count(owner_engine, table) == 0
    (attempt,) = _attempts(owner_engine)
    assert attempt.status == "FAILED" and attempt.dataset_version_id is None


@pytest.mark.parametrize("period", ["2026-13", "202610", "2026-1", "2999-01"])
def test_fr_003_7_invalid_period_is_rejected(
    client: TestClient, analyst: dict[str, str], owner_engine: Engine, period: str
) -> None:
    response = client.post(
        f"/api/v1/datasets/SUPINV/periods/{period}/ingestions", files=_files(), headers=analyst
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_PERIOD"
    assert _count(owner_engine, "app.dataset_periods") == 0


def test_fr_003_7_period_may_be_at_most_one_month_ahead() -> None:
    from datetime import date

    validate_period("2027-01", date(2026, 12, 15))
    with pytest.raises(SentinelError):
        validate_period("2027-02", date(2026, 12, 15))


def test_fr_004_5_and_6_new_version_supersedes_and_duplicate_content_does_not(
    client: TestClient, analyst: dict[str, str], owner_engine: Engine
) -> None:
    v1 = client.post(URL, files=_files(), headers=analyst).json()["version"]

    start = len(audit_events(owner_engine))
    again = client.post(URL, files=_files(), headers=analyst)
    assert again.status_code == 200
    assert again.json()["attempt"]["status"] == "DUPLICATE_CONTENT"
    assert again.json()["version"]["label"] == v1["label"]
    assert _count(owner_engine, "app.dataset_versions") == 1
    assert [e["event_type"] for e in audit_events(owner_engine)[start:]] == ["INGESTION_DUPLICATE"]

    start = len(audit_events(owner_engine))
    changed = INVOICES.replace(b"120.00", b"121.00")
    v2 = client.post(URL, files=_files(invoices=changed), headers=analyst)
    assert v2.status_code == 201 and v2.json()["version"]["label"] == "SUPINV-2026-10-v2"
    assert v2.json()["version"]["content_hash"] != v1["content_hash"]
    assert [e["event_type"] for e in audit_events(owner_engine)[start:]] == [
        "VERSION_CREATED",
        "VERSION_SUPERSEDED",
    ]
    old = client.get(f"/api/v1/versions/{v1['id']}").json()
    assert old["status"] == "SUPERSEDED" and old["derived_state"] == "SUPERSEDED"
    assert client.get(f"/api/v1/versions/{v1['id']}/raw-files/invoices").content == INVOICES
    detail = client.get(f"/api/v1/datasets/SUPINV/periods/{PERIOD}").json()
    assert [v["seq"] for v in detail["versions"]] == [2, 1]
    assert len(detail["ingestion_attempts"]) == 3


def test_ingestion_requires_the_analyst_role(client: TestClient, make_user: Any) -> None:
    make_user("approver_ing", Role.APPROVER)
    csrf = login(client, "approver_ing")
    response = client.post(URL, files=_files(), headers={"X-CSRF-Token": csrf})
    assert response.status_code == 403
    make_user("admin_ing", Role.ADMIN)
    login(client, "admin_ing")
    assert (
        client.get("/api/v1/versions/00000000-0000-4000-8000-000000000000/raw-files/x").status_code
        == 403
    )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE data.version_rows SET cells = '{}'",
        "DELETE FROM data.version_rows",
        "TRUNCATE data.version_rows",
        "UPDATE data.raw_files SET bytes = ''",
        "DELETE FROM data.raw_files",
        "UPDATE app.dataset_versions SET content_hash = repeat('0', 64)",
        "DELETE FROM app.dataset_versions",
        "UPDATE app.ingestion_attempts SET status = 'SUCCEEDED'",
        # Sealed: rows cannot be added to an existing version in a later transaction.
        "INSERT INTO data.version_rows SELECT id, 'invoices', 99, '{}' FROM app.dataset_versions",
    ],
)
def test_fr_004_3_version_content_is_immutable_for_the_app_role(
    client: TestClient, analyst: dict[str, str], app_engine: Engine, statement: str
) -> None:
    assert client.post(URL, files=_files(), headers=analyst).status_code == 201
    with pytest.raises(DBAPIError) as exc, app_engine.begin() as conn:
        conn.execute(text(statement))
    assert isinstance(exc.value.orig, errors.InsufficientPrivilege), exc.value.orig


def test_version_status_only_moves_to_superseded(
    client: TestClient, analyst: dict[str, str], app_engine: Engine
) -> None:
    client.post(URL, files=_files(), headers=analyst)
    with app_engine.begin() as conn:
        conn.execute(text("UPDATE app.dataset_versions SET status = 'SUPERSEDED'"))
    with pytest.raises(DBAPIError, match="sentinel:"), app_engine.begin() as conn:
        conn.execute(text("UPDATE app.dataset_versions SET status = 'ACTIVE'"))
