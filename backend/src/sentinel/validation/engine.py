"""Run execution: evaluate every rule, build findings, write them in one transaction (ARD §8.4).

Execution order and presentation order are separate (FS §4.1). Each table's primary-key rule
is evaluated first because every other rule needs its result for the record-key fallback.
Findings are then written, and always read back, in ascending rule-ID order.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, func, insert, select

from sentinel.config.models import Contract, Rule, RuleSet
from sentinel.validation.rules import Compiled, RunContext, compile_rule, is_primary_key_rule
from sentinel.validation.tables import finding_records, findings

MAX_SAMPLES = 20  # FR-009
SEVERITIES = ("BLOCKING", "WARNING", "INFO")

MESSAGES = {
    "required_column": "{count} required column(s) missing from {table}: {names}.",
    "required_column_extra": "{count} unexpected column(s) in {table}: {names}.",
    "not_null": "{count} {table} record(s) have a missing value in {names}.",
    "type_parse": "{count} {table} record(s) have a value that is not a valid {kinds} in {names}.",
    "allowed_values": "{count} {table} record(s) have a value outside the allowed list in {names}.",
    "range": "{count} {table} record(s) have {names} outside the permitted range.",
    "column_comparison": "{count} {table} record(s) fail the comparison between {names}.",
    "arithmetic_check": "{count} {table} record(s) do not add up across {names}.",
    "date_window": "{count} {table} record(s) have {names} outside the permitted dates.",
    "duplicate_rows": "{groups} group(s) of identical {table} rows ({count} records).",
    "unique": "{groups} duplicate group(s) ({count} records) share {names} in {table}.",
    "foreign_key": "{count} {table} record(s) reference a {names} that does not exist.",
    "cross_table_condition": "{count} {table} record(s) conflict with a related record ({names}).",
}


@dataclass
class FindingDraft:
    rule: Rule
    columns: list[str]
    failing_count: int
    evaluated_count: int
    records: list[dict[str, Any]] = field(default_factory=list)
    samples: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    message_key: str | None = None
    id: UUID = field(default_factory=uuid4)


@dataclass
class RunOutcome:
    """What a completed evaluation produced. Passed to later steps such as impact."""

    run_id: UUID
    ctx: RunContext
    rules: RuleSet
    findings: dict[str, UUID]  # rule ID -> finding ID, for rules that failed
    truncated: set[str]
    finding_counts: dict[str, int]
    not_evaluated: list[dict[str, Any]]


RuleHook = Callable[[Rule], None]


def _schema_finding(rule: Rule, contract: Contract, observed: list[str]) -> FindingDraft | None:
    table = contract.tables[rule.table]
    mode = rule.parsed.mode  # type: ignore[attr-defined]
    if mode == "missing":
        names = [c for c in table.required_columns if c not in observed]
        key, total = "required_column", len(table.required_columns)
    else:
        names = [c for c in observed if c not in table.column_names]
        key, total = "required_column_extra", len(observed)
    if not names:
        return None
    return FindingDraft(rule, names, len(names), total, details={mode: names}, message_key=key)


def _missing_required(rule: Rule, contract: Contract, observed: dict[str, list[str]]) -> list[str]:
    """Required columns the rule reads that the upload does not have (FR-007)."""
    missing = []
    for table, column in rule.parsed.referenced(rule.table, contract):
        definition = contract.tables[table].column(column)
        if definition is not None and definition.required and column not in observed.get(table, []):
            name = f"{table}.{column}"
            if name not in missing:
                missing.append(name)
    return missing


def _evaluate(
    conn: Connection, rule: Rule, compiled: Compiled, evaluated: int, cap: int,
    duplicated_keys: set[int],
) -> FindingDraft | None:  # fmt: skip
    failing = compiled.query.subquery("f")
    keys = [failing.c[f"k{i}"] for i in range(compiled.keys)]
    rows = conn.execute(
        select(failing, func.count().over().label("total"))
        .order_by(*keys, failing.c.row_num)
        .limit(cap)
    ).all()
    if not rows:
        return None
    draft = FindingDraft(rule, compiled.columns, rows[0].total, evaluated)
    draft.truncated = draft.failing_count > len(rows)
    group_no, previous = 0, None
    for ordinal, row in enumerate(rows, start=1):
        blank = row.pk is None or not row.pk.strip(" ")
        key = f"#{row.row_num}" if blank or row.row_num in duplicated_keys else row.pk
        record = {"ordinal": ordinal, "row_num": row.row_num, "record_key": key,
                  "group_no": None, "is_canonical": None}  # fmt: skip
        if compiled.grouped and row.first_row is not None:
            group_key = tuple(row._mapping[f"k{i}"] for i in range(compiled.keys))
            if group_key != previous:
                group_no, previous = group_no + 1, group_key
            record["group_no"] = group_no
            record["is_canonical"] = row.row_num == row.first_row
        draft.records.append(record)
        if ordinal <= MAX_SAMPLES:
            values = {c: row._mapping[f"v{i}"] for i, c in enumerate(compiled.columns)}
            draft.samples.append({"row_num": row.row_num, "values": values})
    if compiled.grouped:
        draft.details["groups"] = group_no
    return draft


def _message(draft: FindingDraft, contract: Contract) -> str:
    rule = draft.rule
    table = contract.tables[rule.table]
    kinds = sorted({c.kind for c in table.columns if c.name in draft.columns})
    return MESSAGES[draft.message_key or rule.type].format(
        count=draft.failing_count,
        groups=draft.details.get("groups", 0),
        table=rule.table,
        names=", ".join(draft.columns),
        kinds=" or ".join(kinds),
    )


def evaluate_rules(
    conn: Connection,
    run_id: UUID,
    ctx: RunContext,
    rules: RuleSet,
    observed: dict[str, list[str]],
    row_counts: dict[str, int],
    cap: int,
    before_rule: RuleHook | None = None,
) -> RunOutcome:
    """Evaluate the rule set and write findings and records. The caller owns the transaction."""
    contract = ctx.contract
    ordered: Sequence[Rule] = sorted(
        rules.rules, key=lambda r: (not is_primary_key_rule(r, contract), r.id)
    )
    drafts: list[FindingDraft] = []
    not_evaluated: list[dict[str, Any]] = []
    duplicated: dict[str, set[int]] = {}
    for rule in ordered:
        if before_rule is not None:
            before_rule(rule)
        if rule.table not in contract.tables or rule.table not in observed:
            not_evaluated.append({"rule_id": rule.id, "missing_columns": [f"{rule.table}.*"]})
            continue
        if rule.type == "required_column":
            schema = _schema_finding(rule, contract, observed[rule.table])
            if schema is not None:
                drafts.append(schema)
            continue
        missing = _missing_required(rule, contract, observed)
        if missing:
            not_evaluated.append({"rule_id": rule.id, "missing_columns": missing})
            continue
        primary = is_primary_key_rule(rule, contract)
        draft = _evaluate(
            conn, rule, compile_rule(rule, ctx), row_counts.get(rule.table, 0), cap,
            set() if primary else duplicated.get(rule.table, set()),
        )  # fmt: skip
        if draft is None:
            continue
        if primary:
            # Every row this rule reports has a null or duplicated key: it gets `#<row_num>`.
            duplicated[rule.table] = {r["row_num"] for r in draft.records}
            for record in draft.records:
                record["record_key"] = f"#{record['row_num']}"
        drafts.append(draft)

    drafts.sort(key=lambda d: d.rule.id)  # stored in rule-ID order whatever the execution order
    counts = dict.fromkeys(SEVERITIES, 0)
    for draft in drafts:
        counts[draft.rule.severity] += 1
        conn.execute(
            insert(findings).values(
                id=draft.id,
                run_id=run_id,
                rule_id=draft.rule.id,
                rule_type=draft.rule.type,
                severity=draft.rule.severity,
                waivable=draft.rule.is_waivable,
                table_name=draft.rule.table,
                columns=draft.columns,
                failing_count=draft.failing_count,
                evaluated_count=draft.evaluated_count,
                truncated=draft.truncated,
                samples=draft.samples,
                message=_message(draft, contract),
                details=draft.details,
            )
        )
        if draft.records:
            conn.execute(
                insert(finding_records), [{"finding_id": draft.id, **r} for r in draft.records]
            )
    return RunOutcome(
        run_id=run_id,
        ctx=ctx,
        rules=rules,
        findings={d.rule.id: d.id for d in drafts},
        truncated={d.rule.id for d in drafts if d.truncated},
        finding_counts=counts,
        not_evaluated=sorted(not_evaluated, key=lambda n: n["rule_id"]),
    )
