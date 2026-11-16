"""Issues, waivers, review, approval and staleness (FR-010, FR-013, FR-014, BR-003 to BR-006)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from sentinel.shared.authz import Role
from tests import reference
from tests.conftest import audit_events, login

pytestmark = pytest.mark.db
JUSTIFICATION = "Supplier master data is loaded a day later than invoices."


@pytest.fixture(scope="session")
def datasets(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("reference-review")


class Actors:
    def __init__(self, client: TestClient, make_user: Any) -> None:
        self.app = client.app
        make_user("rv_analyst", Role.ANALYST)
        make_user("rv_approver", Role.APPROVER)
        make_user("rv_both", Role.ANALYST, Role.APPROVER)
        self.analyst, self.analyst_h = self._session("rv_analyst")
        self.approver, self.approver_h = self._session("rv_approver")
        self.both, self.both_h = self._session("rv_both")

    def _session(self, username: str) -> tuple[TestClient, dict[str, str]]:
        client = TestClient(self.app)
        return client, {"X-CSRF-Token": login(client, username)}


@pytest.fixture
def actors(client: TestClient, make_user: Any) -> Actors:
    return Actors(client, make_user)


def _validated(
    actors: Actors, datasets: Path, dataset: str = "corrected"
) -> tuple[dict[str, Any], dict[str, Any]]:
    directory = reference.generate(datasets, dataset)
    version = reference.upload_dataset(actors.analyst, actors.analyst_h, directory)
    return version, reference.completed(actors.analyst, actors.analyst_h, version["id"])


def _issues(actors: Actors, run_id: str) -> dict[str, dict[str, Any]]:
    items = actors.analyst.get(f"/api/v1/runs/{run_id}/issues").json()["items"]
    return {i["rule_id"]: i for i in items}


def _code(response: Any) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


def _waive(actors: Actors, issue_id: str) -> dict[str, Any]:
    waiver = actors.analyst.post(
        f"/api/v1/issues/{issue_id}/waivers",
        json={"category": "KNOWN_SOURCE_LIMITATION", "justification": JUSTIFICATION},
        headers=actors.analyst_h,
    )
    assert waiver.status_code == 201, waiver.text
    granted = actors.approver.post(
        f"/api/v1/waivers/{waiver.json()['id']}/decision",
        json={"decision": "GRANT"},
        headers=actors.approver_h,
    )
    assert granted.status_code == 200 and granted.json()["status"] == "GRANTED", granted.text
    result: dict[str, Any] = granted.json()
    return result


def _state(actors: Actors, version_id: str) -> str:
    state: str = actors.analyst.get(f"/api/v1/versions/{version_id}").json()["derived_state"]
    return state


def test_fr_010_1_one_issue_per_blocking_or_warning_finding(actors: Actors, datasets: Path) -> None:
    _, run = _validated(actors, datasets, "defective")
    issues = _issues(actors, run["id"])
    counts = run["finding_counts"]
    assert len(issues) == counts["BLOCKING"] + counts["WARNING"] == 16
    assert {i["state"] for i in issues.values()} == {"OPEN"}
    assert issues["INV_FK_SUPPLIER"]["allowed_transitions"] == ["WAIVER_REQUESTED"]
    assert issues["INV_PK_UNIQUE"]["allowed_transitions"] == []
    only_blocking = actors.analyst.get(f"/api/v1/runs/{run['id']}/issues?severity=BLOCKING").json()
    assert only_blocking["total"] == counts["BLOCKING"]


def test_fr_013_waiver_rules_and_segregation_of_duties(
    actors: Actors, datasets: Path, owner_engine: Engine
) -> None:
    _, run = _validated(actors, datasets, "defective")
    issues = _issues(actors, run["id"])
    fk = issues["INV_FK_SUPPLIER"]["id"]
    url = f"/api/v1/issues/{fk}/waivers"
    good = {"category": "KNOWN_SOURCE_LIMITATION", "justification": JUSTIFICATION}

    # FR-013.1
    assert _code(
        actors.analyst.post(
            url, json={**good, "justification": "too short"}, headers=actors.analyst_h
        )
    ) == (422, "VALIDATION_ERROR")
    assert _code(
        actors.analyst.post(url, json={"justification": JUSTIFICATION}, headers=actors.analyst_h)
    ) == (422, "VALIDATION_ERROR")
    # FR-013.2 and FR-013.3
    pk = f"/api/v1/issues/{issues['INV_PK_UNIQUE']['id']}/waivers"
    assert _code(actors.analyst.post(pk, json=good, headers=actors.analyst_h)) == (
        409,
        "RULE_NOT_WAIVABLE",
    )
    warning = f"/api/v1/issues/{issues['INV_OUT_OF_PERIOD']['id']}/waivers"
    assert _code(actors.analyst.post(warning, json=good, headers=actors.analyst_h)) == (
        409,
        "WAIVER_NOT_APPLICABLE",
    )
    assert actors.approver.post(url, json=good, headers=actors.approver_h).status_code == 403

    # A user holding both roles requests, then cannot decide their own request (FR-013.4).
    waiver = actors.both.post(url, json=good, headers=actors.both_h)
    assert waiver.status_code == 201 and waiver.json()["status"] == "REQUESTED"
    decide = f"/api/v1/waivers/{waiver.json()['id']}/decision"
    assert _code(actors.both.post(decide, json={"decision": "GRANT"}, headers=actors.both_h)) == (
        403,
        "SEGREGATION_OF_DUTIES",
    )
    # FR-010.2: an invalid transition lists what is allowed.
    again = actors.analyst.post(url, json=good, headers=actors.analyst_h)
    assert _code(again) == (409, "INVALID_TRANSITION")
    assert again.json()["error"]["details"]["allowed_transitions"] == ["WAIVED", "OPEN"]
    # FR-013.5: a denial needs a comment. A denied waiver returns the issue to OPEN.
    assert _code(
        actors.approver.post(decide, json={"decision": "DENY"}, headers=actors.approver_h)
    ) == (422, "VALIDATION_ERROR")
    denied = actors.approver.post(
        decide,
        json={"decision": "DENY", "comment": "Not enough evidence."},
        headers=actors.approver_h,
    )
    assert denied.status_code == 200 and denied.json()["status"] == "DENIED"
    assert _issues(actors, run["id"])["INV_FK_SUPPLIER"]["state"] == "OPEN"
    assert _code(
        actors.approver.post(decide, json={"decision": "GRANT"}, headers=actors.approver_h)
    ) == (409, "INVALID_TRANSITION")

    granted = _waive(actors, fk)
    assert granted["decided_by"]["display_name"] == "Rv Approver"
    detail = actors.analyst.get(f"/api/v1/issues/{fk}").json()
    assert detail["issue"]["state"] == "WAIVED"
    assert [w["status"] for w in detail["waivers"]] == ["DENIED", "GRANTED"]
    assert detail["finding"]["rule_id"] == "INV_FK_SUPPLIER"
    types = [e["event_type"] for e in audit_events(owner_engine)]
    assert types.count("WAIVER_REQUESTED") == 2
    assert types.count("WAIVER_DENIED") == 1 and types.count("WAIVER_GRANTED") == 1


def test_segregation_trigger_blocks_a_direct_self_decision(
    actors: Actors, datasets: Path, app_engine: Engine
) -> None:
    _, run = _validated(actors, datasets)
    fk = _issues(actors, run["id"])["INV_FK_SUPPLIER"]["id"]
    waiver = actors.analyst.post(
        f"/api/v1/issues/{fk}/waivers",
        json={"category": "OTHER", "justification": JUSTIFICATION},
        headers=actors.analyst_h,
    ).json()
    with pytest.raises(DBAPIError, match="segregation of duties"), app_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app.waiver_decisions (waiver_id, decision, decided_by)"
                " SELECT id, 'GRANT', requested_by FROM app.waivers WHERE id = :id"
            ),
            {"id": waiver["id"]},
        )


def test_fr_010_3_notes_are_append_only_and_audited(
    actors: Actors, datasets: Path, app_engine: Engine, owner_engine: Engine
) -> None:
    _, run = _validated(actors, datasets)
    issue = _issues(actors, run["id"])["INV_OUT_OF_PERIOD"]["id"]
    url = f"/api/v1/issues/{issue}/notes"
    note = actors.approver.post(
        url, json={"body": "Checked with AP: late postings."}, headers=actors.approver_h
    )
    assert note.status_code == 201 and note.json()["author"]["display_name"] == "Rv Approver"
    assert (
        actors.analyst.post(url, json={"body": "   "}, headers=actors.analyst_h).status_code == 422
    )
    assert [n["body"] for n in actors.analyst.get(f"/api/v1/issues/{issue}").json()["notes"]] == [
        "Checked with AP: late postings."
    ]
    event = next(e for e in audit_events(owner_engine) if e["event_type"] == "ISSUE_NOTE_ADDED")
    assert "late postings" not in str(event["payload"])
    for statement in ("UPDATE app.issue_notes SET body = 'x'", "DELETE FROM app.issue_notes"):
        with pytest.raises(DBAPIError), app_engine.begin() as conn:
            conn.execute(text(statement))
    for method in ("put", "patch", "delete"):
        assert getattr(actors.analyst, method)(url, headers=actors.analyst_h).status_code == 405


def test_fr_014_review_and_approval_rules(actors: Actors, datasets: Path) -> None:
    directory = reference.generate(datasets, "corrected")
    version = reference.upload_dataset(actors.analyst, actors.analyst_h, directory)
    submit = f"/api/v1/versions/{version['id']}/review-requests"
    assert _code(actors.analyst.post(submit, json={"note": "Ready"}, headers=actors.analyst_h)) == (
        409,
        "NO_CURRENT_VALIDATION",
    )
    run = reference.completed(actors.analyst, actors.analyst_h, version["id"])
    assert _code(actors.analyst.post(submit, json={"note": " "}, headers=actors.analyst_h)) == (
        422,
        "VALIDATION_ERROR",
    )
    assert (
        actors.approver.post(submit, json={"note": "x"}, headers=actors.approver_h).status_code
        == 403
    )

    # Submitted by a user who holds both roles, to prove self-approval is refused by user ID.
    request = actors.both.post(
        submit, json={"note": "October close, ready for review."}, headers=actors.both_h
    )
    assert request.status_code == 201 and request.json()["status"] == "OPEN"
    assert _state(actors, version["id"]) == "IN_REVIEW"
    assert _code(actors.analyst.post(submit, json={"note": "again"}, headers=actors.analyst_h)) == (
        409,
        "REVIEW_ALREADY_OPEN",
    )

    summary = actors.approver.get(f"/api/v1/versions/{version['id']}/review-summary").json()
    warnings = summary["open_warning_count"]
    assert warnings == run["finding_counts"]["WARNING"] > 0
    assert summary["blocking_unwaived_count"] == 1 and summary["blocking_non_waivable_count"] == 0
    assert summary["differences"] == [] and summary["snapshot"] == summary["live"]

    decide = f"/api/v1/review-requests/{request.json()['id']}/decision"
    approve = {"decision": "APPROVE", "acknowledged_warning_count": warnings}
    assert _code(actors.both.post(decide, json=approve, headers=actors.both_h)) == (
        403,
        "SEGREGATION_OF_DUTIES",
    )
    wrong = actors.approver.post(
        decide,
        json={**approve, "acknowledged_warning_count": warnings - 1},
        headers=actors.approver_h,
    )
    assert _code(wrong) == (409, "WARNING_COUNT_MISMATCH")
    assert wrong.json()["error"]["details"]["open_warning_count"] == warnings
    assert _code(
        actors.approver.post(decide, json={"decision": "REJECT"}, headers=actors.approver_h)
    ) == (422, "VALIDATION_ERROR")

    # A waiver granted after submission shows up as a difference between snapshot and live.
    _waive(actors, _issues(actors, run["id"])["INV_FK_SUPPLIER"]["id"])
    summary = actors.approver.get(f"/api/v1/versions/{version['id']}/review-summary").json()
    assert set(summary["differences"]) == {"issue_counts", "granted_waivers"}
    assert summary["blocking_unwaived_count"] == 0

    approved = actors.approver.post(decide, json=approve, headers=actors.approver_h)
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"
    assert approved.json()["acknowledged_warning_count"] == warnings
    assert _state(actors, version["id"]) == "APPROVED"
    assert _code(actors.approver.post(decide, json=approve, headers=actors.approver_h)) == (
        409,
        "INVALID_TRANSITION",
    )

    # A rejected request allows a new submission.
    v2 = reference.upload(
        actors.analyst,
        actors.analyst_h,
        suppliers=(directory / "suppliers.csv").read_bytes(),
        invoices=(directory / "invoices.csv").read_bytes(),
        period="2026-09",
    )
    reference.completed(actors.analyst, actors.analyst_h, v2["id"])
    second = actors.analyst.post(
        f"/api/v1/versions/{v2['id']}/review-requests", json={"note": "n"}, headers=actors.analyst_h
    ).json()
    rejected = actors.approver.post(
        f"/api/v1/review-requests/{second['id']}/decision",
        json={"decision": "REJECT", "comment": "Fix the orphans first."},
        headers=actors.approver_h,
    )
    assert rejected.json()["status"] == "REJECTED" and _state(actors, v2["id"]) == "VALIDATED"
    assert (
        actors.analyst.post(
            f"/api/v1/versions/{v2['id']}/review-requests",
            json={"note": "n2"},
            headers=actors.analyst_h,
        ).status_code
        == 201
    )


def _approved_version(actors: Actors, datasets: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    version, run = _validated(actors, datasets)
    _waive(actors, _issues(actors, run["id"])["INV_FK_SUPPLIER"]["id"])
    request = actors.analyst.post(
        f"/api/v1/versions/{version['id']}/review-requests",
        json={"note": "Ready"},
        headers=actors.analyst_h,
    ).json()
    approved = actors.approver.post(
        f"/api/v1/review-requests/{request['id']}/decision",
        json={
            "decision": "APPROVE",
            "acknowledged_warning_count": run["finding_counts"]["WARNING"],
        },
        headers=actors.approver_h,
    )
    assert approved.status_code == 200, approved.text
    return version, run


def _statuses(owner_engine: Engine) -> dict[str, list[tuple[str, str | None]]]:
    with owner_engine.connect() as conn:
        return {
            "waivers": [
                tuple(r) for r in conn.execute(text("SELECT status, stale_reason FROM app.waivers"))
            ],
            "reviews": [
                tuple(r)
                for r in conn.execute(text("SELECT status, stale_reason FROM app.review_requests"))
            ],
            "issues": sorted(
                {(r[0], None) for r in conn.execute(text("SELECT state FROM app.issues"))}
            ),
        }


def test_br_003_3_a_new_run_makes_earlier_decisions_stale(
    actors: Actors, datasets: Path, owner_engine: Engine
) -> None:
    version, run = _approved_version(actors, datasets)
    assert _state(actors, version["id"]) == "APPROVED"
    start = len(audit_events(owner_engine))
    rerun = reference.completed(actors.analyst, actors.analyst_h, version["id"])
    got = _statuses(owner_engine)
    assert got["waivers"] == [("STALE", "NEW_RUN")] and got["reviews"] == [("STALE", "NEW_RUN")]
    assert _state(actors, version["id"]) == "VALIDATED"
    old = actors.analyst.get(f"/api/v1/runs/{run['id']}/issues").json()["items"]
    assert {i["state"] for i in old} == {"CLOSED_NOT_CURRENT"}
    new = _issues(actors, rerun["id"])
    assert {i["state"] for i in new.values()} == {"OPEN"}
    types = [e["event_type"] for e in audit_events(owner_engine)[start:]]
    assert types.count("WAIVER_STALE") == 1 and types.count("REVIEW_REQUEST_STALE") == 1
    assert "ISSUES_CLOSED_NOT_CURRENT" in types
    # Actions against the old run are refused as stale or closed.
    closed = old[0]["id"]
    response = actors.analyst.post(
        f"/api/v1/issues/{closed}/waivers",
        json={"category": "OTHER", "justification": JUSTIFICATION},
        headers=actors.analyst_h,
    )
    assert response.status_code == 409


def test_pub_003_new_version_and_new_rule_set_make_decisions_stale(
    actors: Actors, datasets: Path, owner_engine: Engine, make_user: Any, config_dir: Path
) -> None:
    version, _ = _approved_version(actors, datasets)
    path = config_dir / "datasets" / "supplier_invoices" / "rules.yaml"
    rules = yaml.safe_load(path.read_text())
    rules["rules"][-1]["severity"] = "INFO"
    path.write_text(yaml.safe_dump(rules))
    make_user("rv_admin", Role.ADMIN)
    admin = TestClient(actors.app)
    csrf = login(admin, "rv_admin")
    assert admin.post("/api/v1/admin/config/reload", headers={"X-CSRF-Token": csrf}).json()[
        "changed"
    ]
    got = _statuses(owner_engine)
    assert got["waivers"] == [("STALE", "RULE_SET_CHANGED")]
    assert got["reviews"] == [("STALE", "RULE_SET_CHANGED")]
    assert got["issues"] == [("CLOSED_NOT_CURRENT", None)]
    assert _state(actors, version["id"]) == "INGESTED"

    # A fresh approval on the new rule set, then a new upload supersedes everything.
    run = reference.completed(actors.analyst, actors.analyst_h, version["id"])
    _waive(actors, _issues(actors, run["id"])["INV_FK_SUPPLIER"]["id"])
    directory = reference.generate(datasets, "clean")
    reference.upload_dataset(actors.analyst, actors.analyst_h, directory)
    got = _statuses(owner_engine)
    assert ("STALE", "VERSION_SUPERSEDED") in got["waivers"]
    assert got["issues"] == [("CLOSED_NOT_CURRENT", None)]
    assert _state(actors, version["id"]) == "SUPERSEDED"
