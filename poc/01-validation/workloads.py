"""PoC-1 workload SQL (ARD §10.1, W1-W9 and W11).

Every statement follows the rules the real engine must follow (ARD §8.4): values and column
names are bound parameters, typed values come only from guarded casts, nothing reads the
clock, and every result is ordered on a stable key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

SUPPLIER_COLUMNS = [
    "supplier_id", "supplier_name", "country_code", "default_currency",
    "status", "active_from", "active_to", "tax_id",
]  # fmt: skip
INVOICE_COLUMNS = [
    "invoice_id", "supplier_id", "supplier_invoice_number", "document_type", "invoice_date",
    "due_date", "currency", "net_amount", "tax_amount", "gross_amount", "status", "description",
]  # fmt: skip
CONTRACT = {"suppliers": SUPPLIER_COLUMNS, "invoices": INVOICE_COLUMNS}
ALLOWED_CURRENCIES = ["GBP", "EUR", "USD"]
ALLOWED_STATUSES = ["RECEIVED", "APPROVED", "PAID", "CANCELLED"]

RULES = [
    "INV_PK_UNIQUE", "INV_TYPE_AMOUNTS", "INV_SIGN_INVOICE", "INV_SIGN_CREDIT", "INV_TYPE_DATES",
    "INV_OUT_OF_PERIOD", "INV_ARITH", "INV_BK_UNIQUE", "INV_DUP_ROWS", "INV_FK_SUPPLIER",
    "INV_SUPPLIER_STATUS", "INV_NN_SUPPLIER", "INV_DUE_BEFORE_INVOICE", "INV_CODE_CURRENCY",
    "INV_CODE_STATUS", "INV_CURRENCY_MISMATCH",
]  # fmt: skip

DECIMAL_RE = r"'^-?[0-9]{1,16}(\.[0-9]{1,2})?$'"
DATE_RE = "'^[0-9]{4}-[0-9]{2}-[0-9]{2}$'"


def col(name: str, alias: str = "r") -> str:
    """A cell read. The column name is validated against the contract and then bound."""
    if name not in SUPPLIER_COLUMNS and name not in INVOICE_COLUMNS:
        raise ValueError(f"unknown contract column {name!r}")
    return f"({alias}.cells ->> %(c_{name})s)"


def not_null(expr: str) -> str:
    return f"NULLIF(btrim({expr}), '') IS NOT NULL"


def dec(expr: str) -> str:
    return f"CASE WHEN {expr} ~ {DECIMAL_RE} THEN {expr}::numeric(18,2) END"


def date(expr: str) -> str:
    return (
        f"CASE WHEN {expr} ~ {DATE_RE} AND pg_input_is_valid({expr}, 'date') "
        f"THEN {expr}::date END"
    )


def record_key(pk: str, row_num: str) -> str:
    """FS §4.1: the primary key, or #<row_num> when it is null or duplicated.

    Duplicated keys are looked up in the INV_PK_UNIQUE finding, which therefore runs first.
    """
    return (
        f"CASE WHEN NULLIF(btrim({pk}), '') IS NULL OR EXISTS (SELECT 1 FROM app.finding_records d"
        f" WHERE d.finding_id = %(f_pk)s AND d.row_num = {row_num})"
        f" THEN '#' || {row_num} ELSE {pk} END"
    )


INVOICES = "data.version_rows r WHERE r.dataset_version_id = %(v)s AND r.table_name = %(t_inv)s"
GROSS, NET, TAX = col("gross_amount"), col("net_amount"), col("tax_amount")
INV_DATE, DUE_DATE = col("invoice_date"), col("due_date")


def supplier_exists(condition: str = "") -> str:
    return (
        "EXISTS (SELECT 1 FROM data.version_rows s WHERE s.dataset_version_id = %(v)s"
        f" AND s.table_name = %(t_sup)s AND {col('supplier_id', 's')} = {col('supplier_id')}"
        f"{condition})"
    )


def record_rule(predicate: str) -> str:
    return f"""
INSERT INTO app.finding_records (finding_id, ordinal, row_num, record_key)
SELECT %(f)s, row_number() OVER (ORDER BY r.row_num), r.row_num,
       {record_key(col("invoice_id"), "r.row_num")}
FROM {INVOICES} AND ({predicate})
ORDER BY r.row_num"""


def group_rule(keys: list[str], where: str, own_key: bool = True) -> str:
    """Rows sharing a key. Canonical = lowest row_num (BR-007). Byte-wise ordering throughout."""
    named = ", ".join(f'({k}) COLLATE "C" AS k{i}' for i, k in enumerate(keys))
    names = ", ".join(f"k{i}" for i in range(len(keys)))
    key = record_key("g.pk", "g.row_num") if own_key else "'#' || g.row_num"
    return f"""
INSERT INTO app.finding_records (finding_id, ordinal, row_num, record_key, group_no, is_canonical)
SELECT %(f)s, row_number() OVER (ORDER BY g.grp, g.row_num), g.row_num, {key}, g.grp,
       g.row_num = g.first_row
FROM (
    SELECT m.*, dense_rank() OVER (ORDER BY {names}) AS grp
    FROM (
        SELECT k.*, count(*) OVER w AS members, min(k.row_num) OVER w AS first_row
        FROM (SELECT r.row_num, {col("invoice_id")} AS pk, {named} FROM {INVOICES} AND {where}) k
        WINDOW w AS (PARTITION BY {names})
    ) m
    WHERE m.members > 1
) g
ORDER BY g.grp, g.row_num"""


# FS §5.3 version totals. Confirmed keys are excluded from potential exposure.
IMPACT_TOTALS = f"""
INSERT INTO app.run_impact_totals
    (run_id, category, currency, amount, record_count, unquantifiable_count)
WITH c_dup AS (
    SELECT DISTINCT fr.row_num FROM app.finding_records fr
    WHERE fr.finding_id = ANY(%(f_confirmed_dup)s) AND fr.is_canonical = false
), c_all AS (
    SELECT row_num FROM c_dup
    UNION
    SELECT fr.row_num FROM app.finding_records fr WHERE fr.finding_id = %(f_arith)s
), p_all AS (
    SELECT fr.row_num FROM app.finding_records fr WHERE fr.finding_id = ANY(%(f_potential)s)
    UNION
    SELECT fr.row_num FROM app.finding_records fr
    WHERE fr.finding_id = %(f_pk)s AND fr.is_canonical = false
    EXCEPT
    SELECT row_num FROM c_all
), members AS (
    SELECT 'CONFIRMED_DISCREPANCY' AS category, c.row_num, d.row_num IS NOT NULL AS whole_amount
    FROM c_all c LEFT JOIN c_dup d USING (row_num)
    UNION ALL
    SELECT 'POTENTIAL_EXPOSURE', p.row_num, true FROM p_all p
), amounts AS (
    SELECT m.category, {col("currency")} AS currency,
           CASE WHEN m.whole_amount THEN {dec(GROSS)}
                ELSE abs({dec(NET)} + {dec(TAX)} - {dec(GROSS)}) END AS amount
    FROM members m
    JOIN data.version_rows r ON r.dataset_version_id = %(v)s AND r.table_name = %(t_inv)s
                            AND r.row_num = m.row_num
)
SELECT %(run)s, category, currency, coalesce(sum(amount), 0), count(*),
       count(*) FILTER (WHERE amount IS NULL)
FROM amounts
GROUP BY category, currency
ORDER BY category, currency"""

# FS §5.4 KPI-02: spend by supplier, as reported and with confirmed duplicates excluded.
KPI_02 = f"""
INSERT INTO app.kpi_values (run_id, kpi_id, scope, currency, supplier_id, value)
SELECT %(run)s, %(kpi_02)s, x.scope, a.currency, a.supplier_id, x.value
FROM (
    SELECT i.currency, i.supplier_id, coalesce(sum(i.amount), 0) AS as_reported,
           coalesce(sum(i.amount) FILTER (WHERE NOT i.excluded), 0) AS fully_adjusted
    FROM (
        SELECT {col("currency")} AS currency, {col("supplier_id")} AS supplier_id,
               {dec(GROSS)} AS amount,
               EXISTS (SELECT 1 FROM app.finding_records fr
                       WHERE fr.finding_id = ANY(%(f_confirmed_dup)s)
                         AND fr.is_canonical = false AND fr.row_num = r.row_num) AS excluded
        FROM {INVOICES}
          AND {col("status")} IS DISTINCT FROM %(cancelled)s
          AND {date(INV_DATE)} BETWEEN %(p_start)s AND %(p_end)s
          AND {supplier_exists()}
    ) i
    GROUP BY i.currency, i.supplier_id
) a
CROSS JOIN LATERAL (VALUES (%(as_reported)s, a.as_reported),
                           (%(fully_adjusted)s, a.fully_adjusted)) x(scope, value)
ORDER BY a.currency COLLATE "C", a.supplier_id COLLATE "C", x.scope"""


@dataclass
class Statement:
    name: str  # rule ID, or a label for aggregate statements
    sql: str
    rule: str | None = None


@dataclass
class Workload:
    id: str
    title: str
    statements: list[Statement] = field(default_factory=list)
    in_w1_w9: bool = True


def rule(rule_id: str, sql: str) -> Statement:
    return Statement(rule_id, sql, rule_id)


def validation_workloads() -> list[Workload]:
    bad = lambda c: f"({not_null(col(c))} AND {dec(col(c))} IS NULL)"  # noqa: E731
    bad_date = lambda c: f"({not_null(col(c))} AND {date(col(c))} IS NULL)"  # noqa: E731
    sup = col("supplier_id")
    return [
        Workload("P0", "Primary-key uniqueness (feeds record keys)", in_w1_w9=False, statements=[
            rule("INV_PK_UNIQUE", group_rule([col("invoice_id")], not_null(col("invoice_id")),
                                             own_key=False)),
        ]),
        Workload("W1", "Typed parse and sign range on amounts", [
            rule("INV_TYPE_AMOUNTS", record_rule(
                f"{bad('net_amount')} OR {bad('tax_amount')} OR {bad('gross_amount')}")),
            rule("INV_SIGN_INVOICE", record_rule(
                f"{col('document_type')} = %(invoice)s AND {dec(GROSS)} <= 0")),
            rule("INV_SIGN_CREDIT", record_rule(
                f"{col('document_type')} = %(credit_note)s AND {dec(GROSS)} >= 0")),
        ]),
        Workload("W2", "Date validity and reporting-period window", [
            rule("INV_TYPE_DATES", record_rule(
                f"{bad_date('invoice_date')} OR {bad_date('due_date')}")),
            rule("INV_OUT_OF_PERIOD", record_rule(
                f"{date(INV_DATE)} < %(p_start)s OR {date(INV_DATE)} > %(p_end)s")),
        ]),
        Workload("W3", "Arithmetic check net + tax = gross", [
            rule("INV_ARITH", record_rule(
                f"abs({dec(NET)} + {dec(TAX)} - {dec(GROSS)}) > %(tolerance)s")),
        ]),
        Workload("W4", "Business-key uniqueness", [
            rule("INV_BK_UNIQUE", group_rule(
                [sup, f"upper(btrim({col('supplier_invoice_number')}))"],
                f"{not_null(sup)} AND {not_null(col('supplier_invoice_number'))}")),
        ]),
        Workload("W5", "Exact duplicate rows", [
            rule("INV_DUP_ROWS", group_rule(
                [f"jsonb_build_array({', '.join(col(c) for c in INVOICE_COLUMNS)})::text"],
                "true")),
        ]),
        Workload("W6", "Referential integrity invoices -> suppliers", [
            rule("INV_FK_SUPPLIER", record_rule(f"{not_null(sup)} AND NOT {supplier_exists()}")),
        ]),
        Workload("W7", "Supplier status and active window", [
            rule("INV_SUPPLIER_STATUS", record_rule(supplier_exists(
                f" AND ({col('status', 's')} = %(blocked)s"
                f" OR {date(INV_DATE)} < {date(col('active_from', 's'))}"
                f" OR {date(INV_DATE)} > {date(col('active_to', 's'))})"))),
        ]),
        Workload("X1", "Remaining catalogue rules (D-03, D-07, D-09, D-11)", in_w1_w9=False,
                 statements=[
            rule("INV_NN_SUPPLIER", record_rule(f"NOT ({not_null(sup)})")),
            rule("INV_DUE_BEFORE_INVOICE", record_rule(f"{date(DUE_DATE)} < {date(INV_DATE)}")),
            rule("INV_CODE_CURRENCY", record_rule(
                f"{not_null(col('currency'))} AND {col('currency')} <> ALL(%(currencies)s)")),
            rule("INV_CODE_STATUS", record_rule(
                f"{not_null(col('status'))} AND {col('status')} <> ALL(%(statuses)s)")),
            rule("INV_CURRENCY_MISMATCH", record_rule(supplier_exists(
                f" AND {col('default_currency', 's')} <> {col('currency')}"))),
        ]),  # fmt: skip
        Workload("W8", "Impact totals, de-duplicated, per currency", [
            Statement("impact_totals", IMPACT_TOTALS),
        ]),
        Workload("W9", "KPI-02 spend by supplier, as reported vs adjusted", [
            Statement("kpi_02", KPI_02),
        ]),
    ]  # fmt: skip


def base_params(version_id: Any, run_id: Any, findings: dict[str, Any], start: Any, end: Any) -> dict:
    params: dict[str, Any] = {f"c_{c}": c for c in SUPPLIER_COLUMNS + INVOICE_COLUMNS}
    params.update(
        v=version_id, run=run_id, t_inv="invoices", t_sup="suppliers", p_start=start, p_end=end,
        tolerance=Decimal("0.01"), invoice="INVOICE", credit_note="CREDIT_NOTE", blocked="BLOCKED",
        cancelled="CANCELLED", currencies=ALLOWED_CURRENCIES, statuses=ALLOWED_STATUSES,
        kpi_02="KPI-02", as_reported="AS_REPORTED", fully_adjusted="FULLY_ADJUSTED",
        f_pk=findings["INV_PK_UNIQUE"], f_arith=findings["INV_ARITH"],
        f_confirmed_dup=[findings["INV_DUP_ROWS"], findings["INV_BK_UNIQUE"]],
        f_potential=[findings[r] for r in (
            "INV_NN_SUPPLIER", "INV_FK_SUPPLIER", "INV_SUPPLIER_STATUS",
            "INV_SIGN_INVOICE", "INV_SIGN_CREDIT", "INV_TYPE_AMOUNTS")],
    )  # fmt: skip
    return params


# W11: typed snapshot. Run only on a version that passes the non-waivable rules.
def publish_statements() -> list[Statement]:
    def typed(table: str, typed_cols: dict[str, str]) -> str:
        exprs = ", ".join(
            {"date": date, "decimal": dec}[typed_cols[c]](col(c)) if c in typed_cols
            else f"NULLIF({col(c)}, '')" for c in CONTRACT[table]
        )  # fmt: skip
        return f"""
INSERT INTO published.{table} (publication_id, {", ".join(CONTRACT[table])})
SELECT %(pub)s, {exprs}
FROM data.version_rows r
WHERE r.dataset_version_id = %(v)s AND r.table_name = %(t)s
ORDER BY r.row_num"""

    return [
        Statement("snapshot_suppliers", typed("suppliers", {"active_from": "date", "active_to": "date"})),
        Statement("snapshot_invoices", typed("invoices", {
            "invoice_date": "date", "due_date": "date",
            "net_amount": "decimal", "tax_amount": "decimal", "gross_amount": "decimal"})),
    ]  # fmt: skip
