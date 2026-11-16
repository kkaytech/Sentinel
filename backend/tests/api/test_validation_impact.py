"""Validation and impact against the generator's defect catalogue (FR-006 to FR-012)."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from psycopg import errors
from sqlalchemy import Engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

from sentinel.config.service import load_files
from sentinel.shared.authz import Role
from sentinel.validation.rules import RunContext, compile_rule, is_primary_key_rule
from sentinel.validation.service import period_bounds
from tests import reference
from tests.conftest import audit_events, login

pytestmark = pytest.mark.db

SUPPLIERS = (
    b"supplier_id,supplier_name,country_code,default_currency,status,active_from,active_to,tax_id\n"
    b"S1,Acme Ltd,GB,GBP,ACTIVE,2020-01-01,,\n"
    b"S2,Blocked GmbH,DE,EUR,BLOCKED,2020-01-01,,\n"
)
HEADER = (
    b"invoice_id,supplier_id,supplier_invoice_number,document_type,invoice_date,due_date,"
    b"currency,net_amount,tax_amount,gross_amount,status,description\n"
)


@pytest.fixture(scope="session")
def datasets(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("reference")


@pytest.fixture
def analyst(client: TestClient, make_user: Any) -> dict[str, str]:
    make_user("analyst_val", Role.ANALYST)
    return {"X-CSRF-Token": login(client, "analyst_val")}


def _validated(
    client: TestClient, analyst: dict[str, str], datasets: Path, dataset: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    directory = reference.generate(datasets, dataset)
    version = reference.upload_dataset(client, analyst, directory)
    run = reference.completed(client, analyst, version["id"])
    return version, run, reference.catalogue(directory)


def _findings(client: TestClient, run_id: str) -> dict[str, dict[str, Any]]:
    items = client.get(f"/api/v1/runs/{run_id}/findings").json()["items"]
    return {f["rule_id"]: f for f in items}


def _records(client: TestClient, finding_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    while True:
        page = client.get(
            f"/api/v1/findings/{finding_id}/records", params={"limit": 200, "offset": len(items)}
        ).json()
        items.extend(page["items"])
        if len(items) >= page["total"]:
            return items


def _small(client: TestClient, analyst: dict[str, str], rows: list[str]) -> dict[str, Any]:
    invoices = HEADER + "".join(r + "\n" for r in rows).encode()
    version = reference.upload(client, analyst, suppliers=SUPPLIERS, invoices=invoices)
    return reference.run(client, analyst, version["id"])


GOOD = "I1,S1,A-1,INVOICE,2026-10-02,2026-11-01,GBP,100.00,20.00,120.00,PAID,ok"


# ---- findings ------------------------------------------------------------------------------
def test_fr_006_1_defective_dataset_matches_the_catalogue_exactly(
    client: TestClient, analyst: dict[str, str], datasets: Path
) -> None:
    """Also FR-007.1, FR-008.1, FR-008.3, FR-008.4, FR-009.1, FR-009.3 and BR-007.3."""
    version, run, cat = _validated(client, analyst, datasets, "defective")
    assert run["status"] == "COMPLETED" and run["is_current"] and run["not_evaluated"] == []
    assert run["reference_date"] == cat["reference_date"] == "2026-11-15"
    expected = cat["expected_findings"]
    found = _findings(client, run["id"])
    assert set(found) == set(expected)
    assert len(expected) == 16
    for rule_id, want in expected.items():
        finding = found[rule_id]
        records = _records(client, finding["id"])
        assert [[r["row_num"], r["record_key"]] for r in records] == want["rows"], rule_id
        assert finding["failing_count"] == len(want["rows"]) and not finding["truncated"]
        assert finding["evaluated_count"] == 2000
        if want["groups"] is None:
            assert all(r["group_no"] is None and r["is_canonical"] is None for r in records)
            continue
        groups: dict[int, list[int]] = {}
        for record in records:
            groups.setdefault(record["group_no"], []).append(record["row_num"])
        assert sorted(sorted(g) for g in groups.values()) == want["groups"], rule_id
        canonical = {r["row_num"] for r in records if r["is_canonical"]}
        assert canonical == {g[0] for g in want["groups"]}, rule_id
        assert finding["details"]["groups"] == len(want["groups"])

    # FR-008.3: a null supplier_id is never also reported as an orphan.
    null_rows = {r[0] for r in expected["INV_NN_SUPPLIER"]["rows"]}
    assert not null_rows & {r[0] for r in expected["INV_FK_SUPPLIER"]["rows"]}
    # FR-008.4: cross-table evidence carries the supplier key alongside the invoice key.
    sample = found["INV_SUPPLIER_STATUS"]["samples"][0]
    assert sample["values"]["supplier_id"].startswith("SUP-")
    # Message templates are deterministic and carry counts only.
    groups = len(expected["INV_BK_UNIQUE"]["groups"])
    records = len(expected["INV_BK_UNIQUE"]["rows"])
    assert found["INV_BK_UNIQUE"]["message"] == (
        f"{groups} duplicate groups in invoices ({records} records) share "
        "supplier_id, supplier_invoice_number."
    )
    counts = run["finding_counts"]
    assert counts["BLOCKING"] + counts["WARNING"] == 16 and counts["INFO"] == 0
    state = client.get(f"/api/v1/versions/{version['id']}").json()
    assert state["derived_state"] == "VALIDATED" and state["finding_counts"] == counts


def test_fr_006_2_clean_dataset_has_no_findings(
    client: TestClient, analyst: dict[str, str], datasets: Path
) -> None:
    _, run, _ = _validated(client, analyst, datasets, "clean")
    assert run["status"] == "COMPLETED"
    assert run["finding_counts"] == {"BLOCKING": 0, "WARNING": 0, "INFO": 0}
    impact = client.get(f"/api/v1/runs/{run['id']}/impact").json()
    assert impact["totals"] == [] and impact["supplier_ranking"] == []
    assert all(k["direction"] == "NONE" for k in impact["kpis"])


def test_corrected_dataset_leaves_one_waivable_blocker_and_the_warnings(
    client: TestClient, analyst: dict[str, str], datasets: Path
) -> None:
    _, run, cat = _validated(client, analyst, datasets, "corrected")
    found = _findings(client, run["id"])
    assert set(found) == set(cat["expected_findings"])
    blocking = [f for f in found.values() if f["severity"] == "BLOCKING"]
    assert [f["rule_id"] for f in blocking] == ["INV_FK_SUPPLIER"] and blocking[0]["waivable"]


def test_fr_006_3_ten_runs_produce_identical_findings(
    client: TestClient, analyst: dict[str, str], datasets: Path, owner_engine: Engine
) -> None:
    version = reference.upload_dataset(client, analyst, reference.generate(datasets, "defective"))
    serialised = set()
    for _ in range(10):
        run = reference.run(client, analyst, version["id"])
        with owner_engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT f.rule_id, f.rule_type, f.severity, f.waivable, f.table_name,"
                    " f.columns,"
                    " f.failing_count, f.evaluated_count, f.truncated, f.samples, f.message,"
                    " f.details, (SELECT jsonb_agg(jsonb_build_array(r.ordinal, r.row_num,"
                    " r.record_key, r.group_no, r.is_canonical) ORDER BY r.ordinal)"
                    " FROM app.finding_records r WHERE r.finding_id = f.id)"
                    " FROM app.findings f WHERE f.run_id = :run ORDER BY f.rule_id"
                ),
                {"run": run["id"]},
            ).all()
        serialised.add(json.dumps([list(r) for r in rows], sort_keys=True, default=str))
        impact = client.get(f"/api/v1/runs/{run['id']}/impact").json()
        serialised.add("impact:" + json.dumps(impact, sort_keys=True))
    assert len(serialised) == 2  # one findings document and one impact document
    runs = client.get(f"/api/v1/versions/{version['id']}/runs").json()["items"]
    assert len(runs) == 10 and [r["is_current"] for r in runs] == [True] + [False] * 9


def test_fr_006_4_engine_error_marks_the_run_error_and_stores_nothing(
    client: TestClient,
    analyst: dict[str, str],
    owner_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentinel.validation import engine

    version = reference.upload(
        client, analyst, suppliers=SUPPLIERS, invoices=HEADER + GOOD.encode()
    )
    real = engine.compile_rule

    def broken(rule: Any, ctx: Any) -> Any:
        if rule.id == "INV_ARITH":
            raise RuntimeError("boom 120.00")
        return real(rule, ctx)

    monkeypatch.setattr(engine, "compile_rule", broken)
    start = len(audit_events(owner_engine))
    run = reference.run(client, analyst, version["id"])
    assert run["status"] == "ERROR" and not run["is_current"]
    assert run["error_detail"] == {"type": "RuntimeError", "rule_id": "INV_ARITH"}
    assert run["finding_counts"] is None
    with owner_engine.connect() as conn:
        for table in ("findings", "finding_records", "impact_figures", "kpi_values"):
            assert conn.execute(text(f"SELECT count(*) FROM app.{table}")).scalar_one() == 0
    events = audit_events(owner_engine)[start:]
    assert [e["event_type"] for e in events] == ["VALIDATION_RUN_STARTED", "VALIDATION_RUN_FAILED"]
    assert "120.00" not in str(events[1]["payload"])
    state = client.get(f"/api/v1/versions/{version['id']}").json()
    assert state["derived_state"] == "VALIDATION_FAILED"  # BR-003.1: an ERROR run is no pass

    monkeypatch.undo()
    assert reference.run(client, analyst, version["id"])["status"] == "COMPLETED"
    assert client.get(f"/api/v1/versions/{version['id']}").json()["derived_state"] == "VALIDATED"


def test_fr_007_2_missing_required_column_gives_one_finding_and_not_evaluated(
    client: TestClient, analyst: dict[str, str]
) -> None:
    header = HEADER.replace(b",gross_amount", b"")
    row = b"I1,S1,A-1,INVOICE,2026-10-02,2026-11-01,GBP,100.00,20.00,PAID,ok\n"
    version = reference.upload(client, analyst, suppliers=SUPPLIERS, invoices=header + row)
    run = reference.run(client, analyst, version["id"])
    found = _findings(client, run["id"])
    assert list(found) == ["INV_SCHEMA_REQUIRED"]
    finding = found["INV_SCHEMA_REQUIRED"]
    assert finding["columns"] == ["gross_amount"] and finding["failing_count"] == 1
    assert finding["severity"] == "BLOCKING" and not finding["waivable"]
    skipped = {n["rule_id"]: n["missing_columns"] for n in run["not_evaluated"]}
    assert set(skipped) == {
        "INV_ARITH", "INV_DUP_ROWS", "INV_NN_GROSS", "INV_SIGN_CREDIT", "INV_SIGN_INVOICE",
        "INV_TYPE_AMOUNTS",
    }  # fmt: skip
    assert skipped["INV_ARITH"] == ["invoices.gross_amount"]


def test_fr_007_3_and_fr_008_small_cases(client: TestClient, analyst: dict[str, str]) -> None:
    run = _small(
        client,
        analyst,
        [
            GOOD,
            # FR-008.2: same supplier, " inv-001" vs "INV-001".
            "I2,S1,INV-001,INVOICE,2026-10-02,2026-11-01,GBP,10.00,2.00,12.00,PAID,",
            "I3,S1, inv-001,INVOICE,2026-10-02,2026-11-01,GBP,10.00,2.00,12.00,PAID,",
            # FR-007.3: whitespace-only is null; it is not also an orphan (FR-008.3).
            "I4,   ,A-4,INVOICE,2026-10-02,2026-11-01,GBP,10.00,2.00,12.00,PAID,",
            # A null primary key is a violation; its record key falls back to the row number.
            ",S1,A-5,INVOICE,2026-10-02,2026-11-01,GBP,10.00,2.00,12.00,PAID,",
            # Blocked supplier and currency mismatch; an extra unknown currency of any length.
            "I6,S2,A-6,INVOICE,2026-10-02,2026-11-01,POUNDS,10.00,2.00,12.00,PAID,",
            # Unparseable amount: reported once by type_parse, skipped by the typed rules.
            'I7,S1,A-7,INVOICE,2026-10-02,2026-11-01,GBP,10.00,2.00,"12,50O.00",PAID,',
            # Invoice dated after the reference date (2026-11-15).
            "I8,S1,A-8,INVOICE,2026-11-20,2026-12-20,GBP,10.00,2.00,12.00,PAID,",
        ],
    )
    assert run["status"] == "COMPLETED"
    found = _findings(client, run["id"])
    keys = {rule: [r["record_key"] for r in _records(client, f["id"])] for rule, f in found.items()}
    assert keys == {
        "INV_BK_UNIQUE": ["I2", "I3"],
        "INV_NN_SUPPLIER": ["I4"],
        "INV_PK_UNIQUE": ["#5"],
        "INV_SUPPLIER_STATUS": ["I6"],
        "INV_CURRENCY_MISMATCH": ["I6"],
        "INV_CODE_CURRENCY": ["I6"],
        "INV_TYPE_AMOUNTS": ["I7"],
        "INV_OUT_OF_PERIOD": ["I8"],
        "INV_FUTURE_DATED": ["I8"],
    }
    bk = _records(client, found["INV_BK_UNIQUE"]["id"])
    assert [(r["group_no"], r["is_canonical"]) for r in bk] == [(1, True), (1, False)]
    # The invalid currency is a finding, and impact is still grouped by it (never an insert error).
    impact = client.get(f"/api/v1/runs/{run['id']}/impact").json()
    assert {"POUNDS", "GBP"} <= {k["currency"] for k in impact["kpis"]}
    potential = {
        t["currency"]: t for t in impact["totals"] if t["category"] == "POTENTIAL_EXPOSURE"
    }
    assert potential["POUNDS"]["amount"] == "12.00"
    assert potential["GBP"]["unquantifiable_count"] == 1  # the unparseable amount


def test_fr_009_2_key_cap_truncates_keys_but_keeps_the_exact_count(
    client: TestClient, analyst: dict[str, str]
) -> None:
    settings = client.app.state.settings  # type: ignore[attr-defined]
    client.app.state.settings = type(settings)(**{**settings.__dict__, "finding_key_cap": 3})  # type: ignore[attr-defined]
    rows = [
        f"I{i},,A-{i},INVOICE,2026-10-02,2026-11-01,GBP,10.00,2.00,12.00,PAID," for i in range(8)
    ]
    run = _small(client, analyst, rows)
    finding = _findings(client, run["id"])["INV_NN_SUPPLIER"]
    assert finding["truncated"] is True and finding["failing_count"] == 8
    assert [r["record_key"] for r in _records(client, finding["id"])] == ["I0", "I1", "I2"]
    figures = client.get(f"/api/v1/findings/{finding['id']}/impact").json()["figures"]
    assert figures[0]["inputs"]["key_list_truncated"] is True


def test_fr_009_4_record_export_neutralises_formula_cells(
    client: TestClient, analyst: dict[str, str]
) -> None:
    run = _small(
        client,
        analyst,
        ['I1,,A-1,INVOICE,2026-10-02,2026-11-01,GBP,10.00,2.00,12.00,PAID,"=HYPERLINK(""x"")"'],
    )
    finding = _findings(client, run["id"])["INV_NN_SUPPLIER"]
    response = client.get(f"/api/v1/findings/{finding['id']}/records.csv")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]["description"] == '\'=HYPERLINK("x")' and rows[0]["record_key"] == "I1"
    record = _records(client, finding["id"])[0]
    assert record["cells"]["description"] == '=HYPERLINK("x")'  # the stored value is untouched
    assert record["failing_columns"] == ["supplier_id"]


# ---- impact --------------------------------------------------------------------------------
def test_fr_011_impact_figures_and_totals_match_the_catalogue(
    client: TestClient, analyst: dict[str, str], datasets: Path
) -> None:
    """FR-011.1, .2, .3, .4 and .5."""
    _, run, cat = _validated(client, analyst, datasets, "defective")
    found = _findings(client, run["id"])
    naive: dict[tuple[str, str], Decimal] = {}
    for rule_id, want in cat["expected_impact_figures"].items():
        body = client.get(f"/api/v1/findings/{found[rule_id]['id']}/impact").json()
        got = {
            f["currency"]: {
                "amount": f["amount"],
                "record_count": f["record_count"],
                "unquantifiable_count": f["inputs"]["unquantifiable_count"],
            }
            for f in body["figures"]
        }
        assert got == want["currencies"], rule_id
        assert {f["category"] for f in body["figures"]} == {want["category"]}
        assert all(f["assumption"] and f["formula_id"] == want["basis"] for f in body["figures"])
        for figure in body["figures"]:
            key = (figure["category"], figure["currency"])
            naive[key] = naive.get(key, Decimal(0)) + Decimal(figure["amount"] or 0)
    # FR-011.2: only the three duplicate and arithmetic rules ever produce a confirmed figure.
    confirmed = {
        r for r, w in cat["expected_impact_figures"].items() if w["category"].startswith("CONF")
    }
    assert confirmed == {"INV_DUP_ROWS", "INV_BK_UNIQUE", "INV_ARITH"}
    rules_without_impact = set(found) - set(cat["expected_impact_figures"])
    for rule_id in rules_without_impact:
        body = client.get(f"/api/v1/findings/{found[rule_id]['id']}/impact").json()
        assert body["figures"] == [], rule_id

    impact = client.get(f"/api/v1/runs/{run['id']}/impact").json()
    totals: dict[str, dict[str, Any]] = {}
    for total in impact["totals"]:
        totals.setdefault(total["category"], {})[total["currency"]] = {
            k: total[k] for k in ("amount", "record_count", "unquantifiable_count")
        }
    assert totals == cat["expected_impact_totals"]
    # FR-011.3: per currency, never combined. FR-011.4: de-duplicated totals differ from the sum.
    assert len(totals["CONFIRMED_DISCREPANCY"]) > 1
    gbp = Decimal(totals["CONFIRMED_DISCREPANCY"]["GBP"]["amount"])
    assert gbp < naive[("CONFIRMED_DISCREPANCY", "GBP")]

    # FR-011.5: re-summing a figure's contributing records reproduces it.
    bk = found["INV_BK_UNIQUE"]
    resummed: dict[str, Decimal] = {}
    for record in _records(client, bk["id"]):
        if record["is_canonical"] is False:
            cells = record["cells"]
            resummed[cells["currency"]] = resummed.get(cells["currency"], Decimal(0)) + Decimal(
                cells["gross_amount"]
            )
    assert {c: f"{v:.2f}" for c, v in resummed.items()} == {
        c: w["amount"]
        for c, w in cat["expected_impact_figures"]["INV_BK_UNIQUE"]["currencies"].items()
    }


def test_fr_012_kpis_match_the_catalogue(
    client: TestClient, analyst: dict[str, str], datasets: Path, owner_engine: Engine
) -> None:
    """FR-012.1 to FR-012.4 and BR-008."""
    _, run, cat = _validated(client, analyst, datasets, "defective")
    impact = client.get(f"/api/v1/runs/{run['id']}/impact").json()
    got: dict[str, dict[str, dict[str, str]]] = {}
    for kpi in impact["kpis"]:
        got.setdefault(kpi["kpi_id"], {})[kpi["currency"]] = {
            "as_reported": kpi["as_reported"],
            "fully_adjusted": kpi["fully_adjusted"],
        }
    assert got == cat["expected_kpis"]

    # FR-012.1: KPI-01 is overstated by exactly the adjusted-away duplicate copies.
    gbp = next(k for k in impact["kpis"] if k["kpi_id"] == "KPI-01" and k["currency"] == "GBP")
    want = cat["expected_kpis"]["KPI-01"]["GBP"]
    assert gbp["direction"] == "OVERSTATED"
    assert Decimal(gbp["delta_abs"]) == Decimal(want["as_reported"]) - Decimal(
        want["fully_adjusted"]
    )
    assert (
        gbp["delta_pct"] == f"{Decimal(gbp['delta_abs']) / Decimal(want['as_reported']) * 100:.2f}"
    )
    assert all(k["assumption"] for k in impact["kpis"])  # FR-012.4

    # FR-012.2: spend per supplier, as reported and adjusted, for every supplier.
    with owner_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT currency, supplier_id, scope, value FROM app.kpi_values "
                "WHERE run_id = :run AND kpi_id = 'KPI-02' AND scope <> 'ISSUE'"
            ),
            {"run": run["id"]},
        ).all()
        issue_rows = conn.execute(
            text("SELECT direction, assumption FROM app.kpi_values WHERE scope = 'ISSUE'")
        ).all()
    by_supplier: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        by_supplier.setdefault((row.currency, row.supplier_id), {})[row.scope.lower()] = (
            f"{row.value:.2f}"
        )
    assert by_supplier == {
        (k["currency"], k["supplier_id"]): {
            "as_reported": k["as_reported"],
            "fully_adjusted": k["fully_adjusted"],
        }
        for k in cat["expected_kpi02"]
    }
    ranking = impact["supplier_ranking"]
    changed = [k for k in cat["expected_kpi02"] if k["as_reported"] != k["fully_adjusted"]]
    assert len(ranking) == impact["supplier_ranking_total"] == len(changed) > 0
    assert [Decimal(r["delta_abs"]) for r in ranking] == sorted(
        (Decimal(r["delta_abs"]) for r in ranking), reverse=True
    )
    assert issue_rows and all(r.assumption for r in issue_rows)  # FR-012.4
    assert {r.direction for r in issue_rows} >= {"OVERSTATED", "INDETERMINATE"}

    # Per-issue effect of the business-key duplicates on KPI-01.
    found = _findings(client, run["id"])
    effects = client.get(f"/api/v1/findings/{found['INV_BK_UNIQUE']['id']}/impact").json()[
        "kpi_effects"
    ]
    assert {e["kpi_id"] for e in effects} == {"KPI-01", "KPI-02", "KPI-03"}
    orphan = client.get(f"/api/v1/findings/{found['INV_FK_SUPPLIER']['id']}/impact").json()
    assert {e["direction"] for e in orphan["kpi_effects"]} == {"INDETERMINATE"}
    assert {e["assumption"] for e in orphan["kpi_effects"]} == {
        "Spend is real but cannot be attributed to a supplier."
    }


def test_br_008_3_credit_notes_are_negative_and_cancelled_invoices_are_excluded(
    client: TestClient, analyst: dict[str, str]
) -> None:
    run = _small(
        client,
        analyst,
        [
            GOOD,
            "I2,S1,A-2,CREDIT_NOTE,2026-10-03,2026-11-02,GBP,-50.00,-10.00,-60.00,PAID,",
            "I3,S1,A-3,INVOICE,2026-10-04,2026-11-03,GBP,1000.00,200.00,1200.00,CANCELLED,",
        ],
    )
    kpis = {k["kpi_id"]: k for k in client.get(f"/api/v1/runs/{run['id']}/impact").json()["kpis"]}
    assert kpis["KPI-01"]["as_reported"] == "60.00"
    assert kpis["KPI-03"]["as_reported"] == "1.00" and kpis["KPI-04"]["as_reported"] == "0.00"


def test_br_007_2_nothing_is_called_a_loss(
    client: TestClient, analyst: dict[str, str], datasets: Path
) -> None:
    _, run, _ = _validated(client, analyst, datasets, "defective")
    found = _findings(client, run["id"])
    documents = [client.get(f"/api/v1/runs/{run['id']}/impact").text]
    documents += [client.get(f"/api/v1/findings/{f['id']}/impact").text for f in found.values()]
    documents.append(json.dumps(client.app.openapi()))  # type: ignore[attr-defined]
    assert not any(re.search(r"\bloss(es)?\b", d, re.IGNORECASE) for d in documents)


# ---- configuration-driven behaviour, currency of runs, guards ---------------------------------
def test_fr_002_4_and_br_003_new_rule_set_needs_a_new_run(
    client: TestClient, analyst: dict[str, str], make_user: Any, config_dir: Path
) -> None:
    version = reference.upload(
        client, analyst, suppliers=SUPPLIERS, invoices=HEADER + GOOD.encode()
    )
    first = reference.run(client, analyst, version["id"])
    assert first["is_current"] and _findings(client, first["id"]) == {}

    path = config_dir / "datasets" / "supplier_invoices" / "rules.yaml"
    rules = yaml.safe_load(path.read_text())
    rules["rules"].append(
        {
            "id": "INV_NET_CEILING",
            "name": "Net amount above the ceiling",
            "type": "range",
            "table": "invoices",
            "params": {"column": "net_amount", "max": "50.00"},
            "severity": "WARNING",
        }
    )
    path.write_text(yaml.safe_dump(rules))
    make_user("admin_val", Role.ADMIN)
    admin = TestClient(client.app)
    csrf = login(admin, "admin_val")
    assert admin.post("/api/v1/admin/config/reload", headers={"X-CSRF-Token": csrf}).json()[
        "changed"
    ]

    # BR-003: the earlier run used an older rule set, so the version has no current run.
    assert client.get(f"/api/v1/runs/{first['id']}").json()["is_current"] is False
    assert client.get(f"/api/v1/versions/{version['id']}").json()["derived_state"] == "INGESTED"
    second = reference.run(client, analyst, version["id"])
    assert second["rule_set_version_id"] != first["rule_set_version_id"] and second["is_current"]
    assert list(_findings(client, second["id"])) == ["INV_NET_CEILING"]  # FR-002.4


def test_run_permissions_and_preconditions(
    client: TestClient, analyst: dict[str, str], make_user: Any, app_engine: Engine
) -> None:
    v1 = reference.upload(client, analyst, suppliers=SUPPLIERS, invoices=HEADER + GOOD.encode())
    make_user("approver_val", Role.APPROVER)
    approver = TestClient(client.app)
    csrf = login(approver, "approver_val")
    url = f"/api/v1/versions/{v1['id']}/runs"
    assert approver.post(url, headers={"X-CSRF-Token": csrf}).status_code == 403
    assert approver.get(url).status_code == 200

    with app_engine.begin() as conn:  # a run left RUNNING blocks another on the same version
        conn.execute(
            text(
                "INSERT INTO app.validation_runs (dataset_version_id, rule_set_version_id,"
                " engine_version, period, reference_date, triggered_by)"
                " SELECT v.id, a.rule_set_version_id, 'x', '2026-10', '2026-11-15', v.created_by"
                " FROM app.dataset_versions v, app.active_config a"
            )
        )
    response = client.post(url, headers=analyst)
    assert response.status_code == 409 and response.json()["error"]["code"] == "RUN_IN_PROGRESS"
    assert client.get(f"/api/v1/versions/{v1['id']}").json()["derived_state"] == "VALIDATING"

    changed = HEADER + GOOD.replace("120.00", "121.00").encode()
    reference.upload(client, analyst, suppliers=SUPPLIERS, invoices=changed)
    response = client.post(url, headers=analyst)
    assert response.status_code == 409 and response.json()["error"]["code"] == "VERSION_SUPERSEDED"
    missing = "/api/v1/versions/00000000-0000-4000-8000-000000000000/runs"
    assert client.post(missing, headers=analyst).json()["error"]["code"] == "VERSION_NOT_FOUND"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE app.validation_runs SET status = 'RUNNING', finished_at = NULL",
        "UPDATE app.validation_runs SET status = 'ERROR'",
        "UPDATE app.validation_runs SET rule_set_version_id = dataset_version_id",
        "DELETE FROM app.validation_runs",
        "UPDATE app.findings SET severity = 'INFO'",
        "DELETE FROM app.finding_records",
        "UPDATE app.impact_figures SET amount = 0",
        "DELETE FROM app.kpi_values",
        "UPDATE app.run_impact_totals SET amount = 0",
        # Sealed: nothing can be added to a completed run.
        "INSERT INTO app.findings (run_id, rule_id, rule_type, severity, waivable, table_name,"
        " columns, failing_count, evaluated_count, truncated, samples, message)"
        " SELECT id, 'X', 'x', 'INFO', false, 't', '{}', 1, 1, false, '[]', 'm'"
        " FROM app.validation_runs",
        "INSERT INTO app.finding_records SELECT id, 9999, 1, 'k' FROM app.findings",
        "INSERT INTO app.run_impact_totals SELECT id, 'POTENTIAL_EXPOSURE', 'ZZZ', 1, 1, 0"
        " FROM app.validation_runs",
    ],
)
def test_completed_runs_are_sealed_for_the_app_role(
    client: TestClient, analyst: dict[str, str], app_engine: Engine, statement: str
) -> None:
    run = _small(client, analyst, [GOOD, GOOD])
    assert run["status"] == "COMPLETED" and run["finding_counts"]["BLOCKING"] == 3
    with pytest.raises(DBAPIError) as exc, app_engine.begin() as conn:
        conn.execute(text(statement))
    assert isinstance(exc.value.orig, errors.InsufficientPrivilege), exc.value.orig


def test_execution_order_work_mem_and_stored_order(
    client: TestClient, analyst: dict[str, str], app_engine: Engine, owner_engine: Engine
) -> None:
    """Primary-key rules run first; findings are stored in rule-ID order; work_mem is local."""
    from sentinel.validation import service as validation

    version = reference.upload(
        client, analyst, suppliers=SUPPLIERS, invoices=HEADER + (GOOD + "\n" + GOOD).encode()
    )
    with app_engine.begin() as conn:
        user = conn.execute(text("SELECT id FROM app.users LIMIT 1")).scalar_one()
        run_id = conn.execute(
            text(
                "INSERT INTO app.validation_runs (dataset_version_id, rule_set_version_id,"
                " engine_version, period, reference_date, triggered_by)"
                " SELECT :v, rule_set_version_id, 'x', '2026-10', '2026-11-15', :u"
                " FROM app.active_config RETURNING id"
            ),
            {"v": version["id"], "u": user},
        ).scalar_one()
    order: list[str] = []
    seen: dict[str, str] = {}

    def capture(conn: Any, outcome: Any) -> None:
        seen["work_mem"] = conn.execute(text("SHOW work_mem")).scalar_one()

    status = validation.execute_run(
        app_engine, run_id, post_steps=[capture], before_rule=lambda rule: order.append(rule.id)
    )
    assert status == "COMPLETED" and seen["work_mem"] == "64MB"
    assert order[:2] == ["INV_PK_UNIQUE", "SUP_PK_UNIQUE"] and order[2:] == sorted(order[2:])
    with app_engine.connect() as conn:
        assert conn.execute(text("SHOW work_mem")).scalar_one() != "64MB"  # not leaked
    with owner_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT rule_id FROM app.findings WHERE run_id = :r ORDER BY ctid"), {"r": run_id}
        ).scalars().all()  # fmt: skip
    assert stored == sorted(stored) == ["INV_BK_UNIQUE", "INV_DUP_ROWS", "INV_PK_UNIQUE"]


def test_rule_sql_is_parameterised_and_reads_no_clock() -> None:
    """ARD §8.4: no now()/CURRENT_DATE/random, and no cell value or column name in SQL text."""
    dataset_dir = Path(__file__).resolve().parents[3] / "config" / "datasets" / "supplier_invoices"
    loaded = load_files(dataset_dir)
    start, end = period_bounds("2026-10")
    from uuid import uuid4

    ctx = RunContext(uuid4(), loaded.contract, start, end, end)
    compiled = 0
    for rule in loaded.rules.rules:
        if rule.type == "required_column":
            continue
        sql = str(compile_rule(rule, ctx).query.compile(dialect=postgresql.dialect()))
        compiled += 1
        assert not re.search(r"now\(|current_date|current_timestamp|random\(|clock_", sql, re.I), (
            rule.id
        )
        for column in loaded.contract.tables[rule.table].column_names:
            assert f"'{column}'" not in sql, (rule.id, column)
        assert "BLOCKED" not in sql and "INVOICE" not in sql and "GBP" not in sql
    assert compiled == 28
    primary = [r.id for r in loaded.rules.rules if is_primary_key_rule(r, loaded.contract)]
    assert primary == ["INV_PK_UNIQUE", "SUP_PK_UNIQUE"]


@pytest.mark.skipif(not os.environ.get("SENTINEL_LOAD_TEST"), reason="set SENTINEL_LOAD_TEST=1")
def test_nfr_001_load_scale_through_the_real_engine(
    client: TestClient, analyst: dict[str, str], datasets: Path
) -> None:
    """100,000 invoices through ingestion, validation and impact, checked against the oracle."""
    directory = reference.generate(datasets, "load-defective", scale="load", dataset="defective")
    cat = reference.catalogue(directory)
    started = time.perf_counter()
    version = reference.upload_dataset(client, analyst, directory)
    ingested = time.perf_counter()
    run = reference.completed(client, analyst, version["id"])
    finished = time.perf_counter()
    found = _findings(client, run["id"])
    assert {r: f["failing_count"] for r, f in found.items()} == {
        r: len(w["rows"]) for r, w in cat["expected_findings"].items()
    }
    impact = client.get(f"/api/v1/runs/{run['id']}/impact").json()
    totals: dict[str, dict[str, Any]] = {}
    for total in impact["totals"]:
        totals.setdefault(total["category"], {})[total["currency"]] = {
            k: total[k] for k in ("amount", "record_count", "unquantifiable_count")
        }
    assert totals == cat["expected_impact_totals"]
    kpis: dict[str, dict[str, dict[str, str]]] = {}
    for kpi in impact["kpis"]:
        kpis.setdefault(kpi["kpi_id"], {})[kpi["currency"]] = {
            "as_reported": kpi["as_reported"],
            "fully_adjusted": kpi["fully_adjusted"],
        }
    assert kpis == cat["expected_kpis"]
    print(f"\nLOAD ingest {ingested - started:.2f}s, validation+impact {finished - ingested:.2f}s")
    assert finished - started <= 60  # NFR-001
