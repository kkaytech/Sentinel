"""Contract and rule set validation (FR-002.1) and the shipped defaults (PRD §12.5, FS §4.2)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from sentinel.config.models import PARAM_MODELS, Contract, RuleSet, validate_rule_set
from sentinel.config.service import load_files
from sentinel.shared.errors import SentinelError

DATASET_DIR = Path(__file__).resolve().parents[3] / "config" / "datasets" / "supplier_invoices"

# BR-004 / PRD §12.5: the exhaustive list of non-waivable BLOCKING rules.
NON_WAIVABLE = {
    "INV_SCHEMA_REQUIRED", "SUP_SCHEMA_REQUIRED", "INV_TYPE_AMOUNTS", "INV_TYPE_DATES",
    "SUP_TYPE_DATES", "INV_PK_UNIQUE", "SUP_PK_UNIQUE", "INV_NN_GROSS", "INV_NN_CURRENCY",
}  # fmt: skip
WAIVABLE = {
    "INV_NN_SUPPLIER", "INV_NN_OTHER", "SUP_NN_OTHER", "INV_DUP_ROWS", "INV_BK_UNIQUE",
    "INV_FK_SUPPLIER", "INV_SIGN_INVOICE", "INV_SIGN_CREDIT", "INV_ARITH",
}  # fmt: skip


def _raw() -> tuple[dict[str, Any], dict[str, Any]]:
    contract = yaml.safe_load((DATASET_DIR / "contract.yaml").read_text())
    rules = yaml.safe_load((DATASET_DIR / "rules.yaml").read_text())
    return contract, rules


def _errors(rules: dict[str, Any]) -> list[str]:
    contract, _ = _raw()
    return validate_rule_set(RuleSet.model_validate(rules), Contract.model_validate(contract))


def test_fr_002_shipped_configuration_is_valid_and_matches_the_catalogue() -> None:
    loaded = load_files(DATASET_DIR)
    by_id = {r.id: r for r in loaded.rules.rules}
    assert len(by_id) == 32
    assert {r.type for r in by_id.values()} == set(PARAM_MODELS)  # all 12 rule types are used
    blocking = {i for i, r in by_id.items() if r.severity == "BLOCKING"}
    assert {i for i in blocking if not by_id[i].is_waivable} == NON_WAIVABLE
    assert {i for i in blocking if by_id[i].is_waivable} == WAIVABLE
    assert {i for i, r in by_id.items() if r.severity == "INFO"} == {
        "INV_SCHEMA_EXTRA",
        "SUP_SCHEMA_EXTRA",
    }
    confirmed = {i for i, r in by_id.items() if r.impact.category == "CONFIRMED_DISCREPANCY"}
    assert confirmed == {"INV_DUP_ROWS", "INV_BK_UNIQUE", "INV_ARITH"}


def test_canonical_hash_ignores_comments_and_key_order(tmp_path: Path) -> None:
    for name in ("contract.yaml", "rules.yaml"):
        (tmp_path / name).write_text("# a comment\n" + (DATASET_DIR / name).read_text())
    assert load_files(tmp_path).hashes == load_files(DATASET_DIR).hashes


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda r: r["rules"][4].update(type="regex_match"), "unknown rule type 'regex_match'"),
        (lambda r: r["rules"][4].update(table="payments"), "unknown table 'payments'"),
        (
            lambda r: r["rules"][4]["params"].update(columns=["net_amount", "vat_amount"]),
            "unknown column invoices.vat_amount",
        ),
        (lambda r: r["rules"][4].update(kpis=["KPI-09"]), "unknown KPI 'KPI-09'"),
        (lambda r: r["rules"][4]["impact"].update(basis="guess"), "unknown impact basis 'guess'"),
        (lambda r: r["rules"][4].pop("waivable"), "must state 'waivable'"),
        (lambda r: r["rules"].append(copy.deepcopy(r["rules"][4])), "duplicate rule ID"),
        (lambda r: r["rules"][4]["params"].update(columns=["status"]), "has no type to parse"),
    ],
)
def test_fr_002_1_invalid_rule_is_rejected_naming_the_item(mutate: Any, expected: str) -> None:
    _, rules = _raw()
    assert rules["rules"][4]["id"] == "INV_TYPE_AMOUNTS"
    mutate(rules)
    errors = _errors(rules)
    assert any(expected in e and "INV_TYPE_AMOUNTS" in e for e in errors), errors


def test_fr_002_custom_sql_and_unknown_keys_are_rejected(tmp_path: Path) -> None:
    contract, rules = _raw()
    rules["rules"][0]["sql"] = "DELETE FROM app.users"
    (tmp_path / "contract.yaml").write_text(yaml.safe_dump(contract))
    (tmp_path / "rules.yaml").write_text(yaml.safe_dump(rules))
    with pytest.raises(SentinelError) as exc:
        load_files(tmp_path)
    assert exc.value.code == "CONFIG_INVALID"
    assert any("sql" in e for e in exc.value.details["errors"])


def test_fr_002_4_a_range_rule_can_be_added_through_configuration_alone() -> None:
    _, rules = _raw()
    rules["rules"].append(
        {
            "id": "INV_NET_CEILING",
            "name": "Net amount above the ceiling",
            "type": "range",
            "table": "invoices",
            "params": {"column": "net_amount", "max": "1000000.00"},
            "severity": "WARNING",
        }
    )
    assert _errors(rules) == []
    rules["rules"][-1]["params"]["max"] = "a lot"
    assert any("'a lot' is not a valid decimal" in e for e in _errors(rules))
