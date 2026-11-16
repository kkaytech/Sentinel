"""Dataset contract and rule set models (FR-002, Doc 4 §5).

Parsing is strict (`extra="forbid"`). `validate_rule_set` then checks every reference against
the contract and returns messages that name the offending item (FR-002.1).
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from sentinel.config.reference import BUNDLED_LISTS

KPI_IDS = ("KPI-01", "KPI-02", "KPI-03", "KPI-04")  # PRD §12.3
IMPACT_BASES = ("non_canonical_gross", "abs_difference", "gross", "abs_gross", "count_only", "none")
COMPARISON_OPS = ("<", "<=", ">", ">=", "=", "!=")
_TYPE_PATTERN = re.compile(r"^(string|date|integer|decimal\(18,2\))$")
_IDENT = r"^[a-z][a-z0-9_]{0,62}$"

Identifier = Annotated[str, Field(pattern=_IDENT)]
ColumnKind = Literal["string", "date", "integer", "decimal"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---- contract ----------------------------------------------------------------------------
class ColumnDef(_Strict):
    name: Identifier
    type: str
    required: bool
    max_length: int | None = Field(default=None, gt=0)
    sensitive: bool = False
    monetary: bool = False
    untrusted_text: bool = False

    @model_validator(mode="after")
    def _known_type(self) -> ColumnDef:
        if not _TYPE_PATTERN.match(self.type):
            raise ValueError(f"column {self.name!r} has unknown type {self.type!r}")
        return self

    @property
    def kind(self) -> ColumnKind:
        return "decimal" if self.type.startswith("decimal") else self.type  # type: ignore[return-value]


class TableDef(_Strict):
    primary_key: list[Identifier] = Field(min_length=1, max_length=1)
    columns: list[ColumnDef] = Field(min_length=1)

    def column(self, name: str) -> ColumnDef | None:
        return next((c for c in self.columns if c.name == name), None)

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    @property
    def required_columns(self) -> list[str]:
        return [c.name for c in self.columns if c.required]


class Relationship(_Strict):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    source: str = Field(alias="from")
    target: str = Field(alias="to")


class Money(_Strict):
    amount_column: str
    currency_column: str


class Contract(_Strict):
    format: Literal["sentinel-contract/v1"]
    dataset_key: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,15}$")
    name: str = Field(min_length=1)
    period_granularity: Literal["month"]
    tables: dict[Identifier, TableDef] = Field(min_length=1)
    relationships: list[Relationship] = []
    money: Money
    reference_lists: dict[Identifier, list[str] | str] = {}

    def reference_list(self, name: str) -> list[str] | None:
        value = self.reference_lists.get(name)
        if isinstance(value, str):
            return BUNDLED_LISTS.get(value)
        return value

    @property
    def money_table(self) -> str:
        return self.money.amount_column.split(".")[0]

    @property
    def amount_column(self) -> str:
        return self.money.amount_column.split(".")[1]

    @property
    def currency_column(self) -> str:
        return self.money.currency_column.split(".")[1]


def validate_contract(contract: Contract) -> list[str]:
    errors: list[str] = []
    for table_name, table in contract.tables.items():
        names = table.column_names
        for dup in sorted({n for n in names if names.count(n) > 1}):
            errors.append(f"table {table_name!r}: duplicate column {dup!r}")
        for key in table.primary_key:
            if key not in names:
                errors.append(f"table {table_name!r}: primary key column {key!r} is not defined")

    def qualified(ref: str, where: str) -> None:
        table, _, column = ref.partition(".")
        if table not in contract.tables or contract.tables[table].column(column) is None:
            errors.append(f"{where}: unknown column {ref!r}")

    for rel in contract.relationships:
        qualified(rel.source, "relationship")
        qualified(rel.target, "relationship")
    qualified(contract.money.amount_column, "money.amount_column")
    qualified(contract.money.currency_column, "money.currency_column")
    if contract.money.amount_column.split(".")[0] != contract.money.currency_column.split(".")[0]:
        errors.append("money: amount and currency columns must be in the same table")
    for name, value in contract.reference_lists.items():
        if isinstance(value, str) and value not in BUNDLED_LISTS:
            errors.append(f"reference list {name!r}: unknown bundled list {value!r}")
    return errors


# ---- rule parameters, one model per rule type (FR-007, FR-008) ------------------------------
class _Params(_Strict):
    def referenced(self, table: str, contract: Contract) -> list[tuple[str, str]]:
        """(table, column) pairs the rule reads. Used for validation and NOT_EVALUATED."""
        return []


class RequiredColumnParams(_Params):
    mode: Literal["missing", "extra"]


class ColumnsParams(_Params):
    columns: list[Identifier] = Field(min_length=1)

    def referenced(self, table: str, contract: Contract) -> list[tuple[str, str]]:
        return [(table, c) for c in self.columns]


class NotNullParams(ColumnsParams):
    pass


class TypeParseParams(ColumnsParams):
    pass


class AllowedValuesParams(_Params):
    column: Identifier
    values: list[str] | None = Field(default=None, min_length=1)
    reference_list: Identifier | None = None

    @model_validator(mode="after")
    def _one_source(self) -> AllowedValuesParams:
        if (self.values is None) == (self.reference_list is None):
            raise ValueError("give exactly one of 'values' or 'reference_list'")
        return self

    def referenced(self, table: str, contract: Contract) -> list[tuple[str, str]]:
        return [(table, self.column)]


class When(_Strict):
    column: Identifier
    equals: str


class RangeParams(_Params):
    column: Identifier
    min: str | None = None
    max: str | None = None
    min_exclusive: bool = False
    max_exclusive: bool = False
    when: When | None = None

    @model_validator(mode="after")
    def _has_bound(self) -> RangeParams:
        if self.min is None and self.max is None:
            raise ValueError("give at least one of 'min' or 'max'")
        return self

    def referenced(self, table: str, contract: Contract) -> list[tuple[str, str]]:
        return [(table, self.column)] + ([(table, self.when.column)] if self.when else [])


class ColumnComparisonParams(_Params):
    left: Identifier
    op: Literal["<", "<=", ">", ">=", "=", "!="]
    right: Identifier

    def referenced(self, table: str, contract: Contract) -> list[tuple[str, str]]:
        return [(table, self.left), (table, self.right)]


class ArithmeticCheckParams(_Params):
    lhs: list[Identifier] = Field(min_length=1)
    op: Literal["sum"]
    rhs: Identifier
    tolerance: str

    def referenced(self, table: str, contract: Contract) -> list[tuple[str, str]]:
        return [(table, c) for c in [*self.lhs, self.rhs]]


class DateWindowParams(_Params):
    column: Identifier
    window: Literal["period", "not_after_reference_date"]

    def referenced(self, table: str, contract: Contract) -> list[tuple[str, str]]:
        return [(table, self.column)]


class DuplicateRowsParams(_Params):
    def referenced(self, table: str, contract: Contract) -> list[tuple[str, str]]:
        return [(table, c) for c in contract.tables[table].column_names]


class UniqueParams(_Params):
    columns: list[Identifier] = Field(min_length=1)
    normalise: dict[Identifier, list[Literal["trim", "upper"]]] = {}
    ignore_nulls: bool = True

    def referenced(self, table: str, contract: Contract) -> list[tuple[str, str]]:
        return [(table, c) for c in self.columns]


class Join(_Strict):
    column: Identifier
    ref_table: Identifier
    ref_column: Identifier


class ForeignKeyParams(_Params):
    column: Identifier
    ref_table: Identifier
    ref_column: Identifier

    def referenced(self, table: str, contract: Contract) -> list[tuple[str, str]]:
        return [(table, self.column), (self.ref_table, self.ref_column)]


class CrossCondition(_Strict):
    """Either `ref_column equals value`, or `column op ref_column`."""

    ref_column: Identifier
    equals: str | None = None
    column: Identifier | None = None
    op: Literal["<", "<=", ">", ">=", "=", "!="] | None = None

    @model_validator(mode="after")
    def _shape(self) -> CrossCondition:
        literal = self.equals is not None
        compare = self.column is not None and self.op is not None
        if literal == compare or (literal and (self.column or self.op)):
            raise ValueError(
                "a condition is either {ref_column, equals} or {column, op, ref_column}"
            )
        return self


class CrossTableConditionParams(_Params):
    join: Join
    any_of: list[CrossCondition] = Field(min_length=1)

    def referenced(self, table: str, contract: Contract) -> list[tuple[str, str]]:
        refs = [(table, self.join.column), (self.join.ref_table, self.join.ref_column)]
        for cond in self.any_of:
            refs.append((self.join.ref_table, cond.ref_column))
            if cond.column is not None:
                refs.append((table, cond.column))
        return refs


PARAM_MODELS: dict[str, type[_Params]] = {
    "required_column": RequiredColumnParams,
    "not_null": NotNullParams,
    "type_parse": TypeParseParams,
    "allowed_values": AllowedValuesParams,
    "range": RangeParams,
    "column_comparison": ColumnComparisonParams,
    "arithmetic_check": ArithmeticCheckParams,
    "date_window": DateWindowParams,
    "duplicate_rows": DuplicateRowsParams,
    "unique": UniqueParams,
    "foreign_key": ForeignKeyParams,
    "cross_table_condition": CrossTableConditionParams,
}


class Impact(_Strict):
    category: Literal["CONFIRMED_DISCREPANCY", "POTENTIAL_EXPOSURE"] | None = None
    basis: str = "none"


class Rule(_Strict):
    id: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    type: str
    table: Identifier
    params: dict[str, Any] = {}
    severity: Literal["BLOCKING", "WARNING", "INFO"]
    waivable: bool | None = None
    impact: Impact = Impact()
    kpis: list[str] = []

    @property
    def parsed(self) -> _Params:
        return PARAM_MODELS[self.type].model_validate(self.params)

    @property
    def is_waivable(self) -> bool:
        return self.severity == "BLOCKING" and bool(self.waivable)


class RuleSet(_Strict):
    format: Literal["sentinel-rules/v1"]
    dataset_key: str
    reference_date_offset_days: int = Field(ge=0, le=366)
    rules: list[Rule] = Field(min_length=1)

    def rule(self, rule_id: str) -> Rule | None:
        return next((r for r in self.rules if r.id == rule_id), None)


def _bound_ok(value: str, kind: str) -> bool:
    try:
        if kind == "decimal":
            Decimal(value)
        elif kind == "integer":
            int(value)
        elif kind == "date":
            date.fromisoformat(value)
        else:
            return False
    except (InvalidOperation, ValueError):
        return False
    return True


def validate_rule_set(rules: RuleSet, contract: Contract) -> list[str]:
    """Semantic checks. Every message names the rule and the offending item (FR-002.1)."""
    errors: list[str] = []
    if rules.dataset_key != contract.dataset_key:
        errors.append(
            f"rule set dataset_key {rules.dataset_key!r} does not match the contract "
            f"({contract.dataset_key!r})"
        )
    seen: set[str] = set()
    for rule in rules.rules:
        where = f"rule {rule.id}"
        if rule.id in seen:
            errors.append(f"{where}: duplicate rule ID")
        seen.add(rule.id)
        if rule.type not in PARAM_MODELS:
            errors.append(f"{where}: unknown rule type {rule.type!r}")
            continue
        if rule.table not in contract.tables:
            errors.append(f"{where}: unknown table {rule.table!r}")
            continue
        try:
            params = rule.parsed
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"]) or "params"
                errors.append(f"{where}: params.{loc}: {err['msg']}")
            continue
        for kpi in rule.kpis:
            if kpi not in KPI_IDS:
                errors.append(f"{where}: unknown KPI {kpi!r}")
        if rule.impact.basis not in IMPACT_BASES:
            errors.append(f"{where}: unknown impact basis {rule.impact.basis!r}")
        elif (rule.impact.basis == "none") != (rule.impact.category is None):
            errors.append(f"{where}: impact needs both a category and a basis other than 'none'")
        elif rule.impact.category is not None and rule.table != contract.money_table:
            errors.append(f"{where}: impact is only supported on table {contract.money_table!r}")
        elif rule.impact.basis == "abs_difference" and rule.type != "arithmetic_check":
            errors.append(f"{where}: impact basis 'abs_difference' needs an arithmetic_check rule")
        elif rule.impact.basis == "non_canonical_gross" and rule.type not in (
            "unique",
            "duplicate_rows",
        ):
            errors.append(f"{where}: impact basis 'non_canonical_gross' needs a duplicate rule")
        if rule.severity == "BLOCKING" and rule.waivable is None:
            errors.append(f"{where}: a BLOCKING rule must state 'waivable'")
        if rule.severity != "BLOCKING" and rule.waivable:
            errors.append(f"{where}: only BLOCKING rules can be waivable")

        unknown = False
        for table, column in params.referenced(rule.table, contract):
            if table not in contract.tables:
                errors.append(f"{where}: unknown table {table!r}")
                unknown = True
            elif contract.tables[table].column(column) is None:
                errors.append(f"{where}: unknown column {table}.{column}")
                unknown = True
        if unknown:
            continue
        errors.extend(f"{where}: {m}" for m in _type_errors(rule, params, contract))
    return errors


def _type_errors(rule: Rule, params: _Params, contract: Contract) -> list[str]:
    table = contract.tables[rule.table]

    def kind(column: str, of: TableDef = table) -> str:
        col = of.column(column)
        assert col is not None
        return col.kind

    out: list[str] = []
    if isinstance(params, TypeParseParams):
        out += [f"column {c!r} is a string and has no type to parse" for c in params.columns
                if kind(c) == "string"]  # fmt: skip
    elif isinstance(params, AllowedValuesParams):
        if (
            params.reference_list is not None
            and contract.reference_list(params.reference_list) is None
        ):
            out.append(f"unknown reference list {params.reference_list!r}")
    elif isinstance(params, RangeParams):
        column_kind = kind(params.column)
        if column_kind == "string":
            out.append(f"column {params.column!r} is a string; range needs a number or date")
        for label, bound in (("min", params.min), ("max", params.max)):
            if bound is not None and column_kind != "string" and not _bound_ok(bound, column_kind):
                out.append(f"{label} {bound!r} is not a valid {column_kind}")
    elif isinstance(params, ColumnComparisonParams):
        if kind(params.left) != kind(params.right):
            out.append(f"columns {params.left!r} and {params.right!r} have different types")
    elif isinstance(params, ArithmeticCheckParams):
        out += [f"column {c!r} is not a decimal" for c in [*params.lhs, params.rhs]
                if kind(c) != "decimal"]  # fmt: skip
        if not _bound_ok(params.tolerance, "decimal") or Decimal(params.tolerance) < 0:
            out.append(f"tolerance {params.tolerance!r} is not a non-negative decimal")
    elif isinstance(params, DateWindowParams):
        if kind(params.column) != "date":
            out.append(f"column {params.column!r} is not a date")
    elif isinstance(params, UniqueParams):
        out += [f"normalise names column {c!r}, which is not in 'columns'" for c in params.normalise
                if c not in params.columns]  # fmt: skip
    elif isinstance(params, CrossTableConditionParams):
        ref = contract.tables[params.join.ref_table]
        for cond in params.any_of:
            if cond.column is not None and kind(cond.column) != kind(cond.ref_column, ref):
                out.append(f"columns {cond.column!r} and {cond.ref_column!r} have different types")
    return out
