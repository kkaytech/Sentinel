"""Rule compiler: one function per rule type, producing SQLAlchemy Core (ARD §8.4).

Rules for the SQL written here:
- Every value and every column name is a bound parameter. Column names are checked against
  the contract when the configuration is loaded.
- A typed value comes only from a guarded cast, which yields NULL for anything unparseable,
  so a rule never raises on dirty data and never double-reports a bad cell (FS §4.1).
- Nothing reads the clock. Dates come from the run (period and reference date).
- Sort keys are compared byte-wise (`COLLATE "C"`), so ordering does not depend on the
  database locale.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Date,
    Integer,
    Numeric,
    Select,
    Text,
    and_,
    case,
    cast,
    collate,
    exists,
    func,
    literal,
    null,
    or_,
    select,
    union_all,
)
from sqlalchemy.sql.selectable import NamedFromClause

from sentinel.config import models as m
from sentinel.config.models import Contract, Rule
from sentinel.ingestion.tables import version_rows

DECIMAL_RE = r"^-?[0-9]{1,16}(\.[0-9]{1,2})?$"
INTEGER_RE = r"^-?[0-9]{1,18}$"
DATE_RE = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
MONEY = Numeric(18, 2)

Expr = ColumnElement[Any]


@dataclass(frozen=True)
class RunContext:
    version_id: UUID
    contract: Contract
    period_start: date
    period_end: date
    reference_date: date


@dataclass(frozen=True)
class Compiled:
    """A query returning the failing rows: `row_num`, `pk`, sample values `v0..`, and for
    grouped rules `first_row` and the group key `k0..`. `order_by` is its stable ordering."""

    query: Select[Any]
    columns: list[str]
    grouped: bool = False
    keys: int = 0


def rows_alias(name: str = "r") -> NamedFromClause:
    return version_rows.alias(name)


def in_table(alias: Any, ctx: RunContext, table: str) -> Expr:
    return and_(alias.c.dataset_version_id == ctx.version_id, alias.c.table_name == table)


def cell(alias: Any, column: str) -> Expr:
    """The raw text of one cell: `cells ->> :column`."""
    return alias.c.cells[column].astext  # type: ignore[no-any-return]


def present(value: Expr) -> Expr:
    """Not null, not empty, not whitespace only (FR-007.3)."""
    return func.nullif(func.btrim(value), "").is_not(None)


def typed(value: Expr, kind: str) -> Expr:
    """The guarded cast for a contract type. Unparseable text becomes NULL."""
    if kind == "decimal":
        return case((value.op("~")(DECIMAL_RE), cast(value, MONEY)), else_=None)
    if kind == "integer":
        return case((value.op("~")(INTEGER_RE), cast(value, BigInteger)), else_=None)
    if kind == "date":
        valid = and_(value.op("~")(DATE_RE), func.pg_input_is_valid(value, "date"))
        return case((valid, cast(value, Date)), else_=None)
    return value


def _kind(ctx: RunContext, table: str, column: str) -> str:
    definition = ctx.contract.tables[table].column(column)
    assert definition is not None  # checked when the configuration was loaded
    return definition.kind


def _value(alias: Any, ctx: RunContext, table: str, column: str) -> Expr:
    return typed(cell(alias, column), _kind(ctx, table, column))


def _literal(value: str, kind: str) -> Any:
    if kind == "decimal":
        return Decimal(value)
    if kind == "integer":
        return int(value)
    if kind == "date":
        return date.fromisoformat(value)
    return value


def _compare(left: Expr, op: str, right: Any) -> Expr:
    comparisons: dict[str, Callable[[Expr, Any], Expr]] = {
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "=": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
    }
    return comparisons[op](left, right)


# ---- record-level predicates (FR-007) and cross-table predicates (FR-008) --------------------
def _not_null(r: Any, p: m.NotNullParams, rule: Rule, ctx: RunContext) -> Expr:
    return or_(*[~present(cell(r, c)) for c in p.columns])


def _type_parse(r: Any, p: m.TypeParseParams, rule: Rule, ctx: RunContext) -> Expr:
    return or_(
        *[and_(present(cell(r, c)), _value(r, ctx, rule.table, c).is_(None)) for c in p.columns]
    )


def _allowed_values(r: Any, p: m.AllowedValuesParams, rule: Rule, ctx: RunContext) -> Expr:
    values = p.values
    if values is None:
        assert p.reference_list is not None
        values = ctx.contract.reference_list(p.reference_list)
    assert values is not None
    return and_(present(cell(r, p.column)), cell(r, p.column).not_in(values))


def _range(r: Any, p: m.RangeParams, rule: Rule, ctx: RunContext) -> Expr:
    kind = _kind(ctx, rule.table, p.column)
    value = _value(r, ctx, rule.table, p.column)
    outside = []
    if p.min is not None:
        bound = _literal(p.min, kind)
        outside.append(value <= bound if p.min_exclusive else value < bound)
    if p.max is not None:
        bound = _literal(p.max, kind)
        outside.append(value >= bound if p.max_exclusive else value > bound)
    violated = or_(*outside)
    if p.when is not None:
        violated = and_(cell(r, p.when.column) == p.when.equals, violated)
    return violated


def _column_comparison(r: Any, p: m.ColumnComparisonParams, rule: Rule, ctx: RunContext) -> Expr:
    left = _value(r, ctx, rule.table, p.left)
    return _compare(left, p.op, _value(r, ctx, rule.table, p.right))


def arithmetic_difference(r: Any, p: m.ArithmeticCheckParams) -> Expr:
    """|sum(lhs) - rhs|, NULL unless every operand parses."""
    total: Expr = typed(cell(r, p.lhs[0]), "decimal")
    for column in p.lhs[1:]:
        total = total + typed(cell(r, column), "decimal")
    return func.abs(total - typed(cell(r, p.rhs), "decimal"))


def _arithmetic_check(r: Any, p: m.ArithmeticCheckParams, rule: Rule, ctx: RunContext) -> Expr:
    return arithmetic_difference(r, p) > Decimal(p.tolerance)


def _date_window(r: Any, p: m.DateWindowParams, rule: Rule, ctx: RunContext) -> Expr:
    value = _value(r, ctx, rule.table, p.column)
    if p.window == "period":
        return or_(value < ctx.period_start, value > ctx.period_end)
    return value > ctx.reference_date


def _foreign_key(r: Any, p: m.ForeignKeyParams, rule: Rule, ctx: RunContext) -> Expr:
    ref = rows_alias("ref")
    match = exists().where(
        in_table(ref, ctx, p.ref_table), cell(ref, p.ref_column) == cell(r, p.column)
    )
    # Nulls are left to not_null, so a row is never reported twice (FR-008.3).
    return and_(present(cell(r, p.column)), ~match)


def _cross_table(r: Any, p: m.CrossTableConditionParams, rule: Rule, ctx: RunContext) -> Expr:
    ref = rows_alias("ref")
    conditions = []
    for cond in p.any_of:
        if cond.equals is not None:
            conditions.append(cell(ref, cond.ref_column) == cond.equals)
        else:
            assert cond.column is not None and cond.op is not None
            conditions.append(
                _compare(
                    _value(r, ctx, rule.table, cond.column),
                    cond.op,
                    _value(ref, ctx, p.join.ref_table, cond.ref_column),
                )
            )
    return exists().where(
        in_table(ref, ctx, p.join.ref_table),
        cell(ref, p.join.ref_column) == cell(r, p.join.column),
        or_(*conditions),
    )


_PREDICATES: dict[str, Callable[[Any, Any, Rule, RunContext], Expr]] = {
    "not_null": _not_null,
    "type_parse": _type_parse,
    "allowed_values": _allowed_values,
    "range": _range,
    "column_comparison": _column_comparison,
    "arithmetic_check": _arithmetic_check,
    "date_window": _date_window,
    "foreign_key": _foreign_key,
    "cross_table_condition": _cross_table,
}


def _sample_columns(rule: Rule, params: Any, ctx: RunContext) -> list[str]:
    """The rule's own columns on its table, in a stable order, without repeats."""
    if isinstance(params, m.DuplicateRowsParams):
        return ctx.contract.tables[rule.table].primary_key
    seen: list[str] = []
    for table, column in params.referenced(rule.table, ctx.contract):
        if table == rule.table and column not in seen:
            seen.append(column)
    return seen


def _base_columns(r: Any, ctx: RunContext, table: str, columns: list[str]) -> list[Any]:
    pk = ctx.contract.tables[table].primary_key[0]
    values = [cell(r, c).label(f"v{i}") for i, c in enumerate(columns)]
    return [r.c.row_num, cell(r, pk).label("pk"), *values]


# ---- set-level rules (FR-008) ----------------------------------------------------------------
def _grouped(
    r: Any,
    rule: Rule, ctx: RunContext, columns: list[str], keys: list[Expr], where: Expr,
    null_rows: Callable[[Any], Expr] | None = None,
) -> Compiled:  # fmt: skip
    """Rows that share a key. `first_row` is the canonical member (lowest row, BR-007)."""
    labelled = [collate(k, "C").label(f"k{i}") for i, k in enumerate(keys)]
    inner = (
        select(*_base_columns(r, ctx, rule.table, columns), *labelled)
        .where(in_table(r, ctx, rule.table), where)
        .subquery("k")
    )
    partition = [inner.c[f"k{i}"] for i in range(len(keys))]
    counted = select(
        inner,
        func.count().over(partition_by=partition).label("members"),
        func.min(inner.c.row_num).over(partition_by=partition).label("first_row"),
    ).subquery("g")
    names = ["row_num", "pk", *[f"v{i}" for i in range(len(columns))]]
    key_names = [f"k{i}" for i in range(len(keys))]
    groups = select(
        *[counted.c[n] for n in names], counted.c.first_row, *[counted.c[n] for n in key_names]
    ).where(counted.c.members > 1)
    if null_rows is None:
        return Compiled(groups, columns, grouped=True, keys=len(keys))
    # A null key is a violation of its own, outside any group ("null counts as a violation").
    n = rows_alias("n")
    nulls = select(
        *_base_columns(n, ctx, rule.table, columns),
        cast(null(), Integer).label("first_row"),
        *[cast(null(), Text).label(name) for name in key_names],
    ).where(in_table(n, ctx, rule.table), null_rows(n))
    combined = union_all(groups, nulls).subquery("u")
    return Compiled(select(combined), columns, grouped=True, keys=len(keys))


def _unique(rule: Rule, p: m.UniqueParams, ctx: RunContext) -> Compiled:
    def key(alias: Any, column: str) -> Expr:
        value = cell(alias, column)
        for step in p.normalise.get(column, []):
            value = func.btrim(value) if step == "trim" else func.upper(value)
        return value

    r = rows_alias()
    all_present = and_(*[present(cell(r, c)) for c in p.columns])

    def any_null(n: Any) -> Expr:
        return or_(*[~present(cell(n, c)) for c in p.columns])

    return _grouped(
        r,
        rule, ctx, list(p.columns), [key(r, c) for c in p.columns], all_present,
        null_rows=None if p.ignore_nulls else any_null,
    )  # fmt: skip


def _duplicate_rows(rule: Rule, p: m.DuplicateRowsParams, ctx: RunContext) -> Compiled:
    r = rows_alias()
    columns = ctx.contract.tables[rule.table].column_names
    # One exact text key over every contract column; JSON keeps NULL distinct from ''.
    key = cast(func.jsonb_build_array(*[cell(r, c) for c in columns]), Text)
    return _grouped(r, rule, ctx, _sample_columns(rule, p, ctx), [key], literal(True))


def compile_rule(rule: Rule, ctx: RunContext) -> Compiled:
    """Compile one configured rule. `required_column` is schema inspection and has no query."""
    params = rule.parsed
    if isinstance(params, m.UniqueParams):
        return _unique(rule, params, ctx)
    if isinstance(params, m.DuplicateRowsParams):
        return _duplicate_rows(rule, params, ctx)
    r = rows_alias()
    columns = _sample_columns(rule, params, ctx)
    predicate = _PREDICATES[rule.type](r, params, rule, ctx)
    query = select(*_base_columns(r, ctx, rule.table, columns)).where(
        in_table(r, ctx, rule.table), predicate
    )
    return Compiled(query, columns)


def is_primary_key_rule(rule: Rule, contract: Contract) -> bool:
    """The rule whose result decides the record-key fallback; it is evaluated first."""
    if rule.type != "unique" or rule.table not in contract.tables:
        return False
    params = rule.parsed
    assert isinstance(params, m.UniqueParams)
    return params.columns == contract.tables[rule.table].primary_key and not params.normalise
