"""Impact computation and queries (FR-011, FR-012; FS §5, ARD §8.5).

All arithmetic is SQL over guarded NUMERIC casts, grouped by the raw currency cell. Deltas,
directions and percentages are derived in Python with `Decimal`. `compute` runs inside the
validation run's completion transaction.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Connection,
    Integer,
    Text,
    case,
    cast,
    exists,
    func,
    insert,
    literal,
    select,
    union_all,
)
from sqlalchemy import null as sql_null

from sentinel.config import models as m
from sentinel.config.models import Contract, Rule
from sentinel.impact.tables import impact_figures, kpi_values, run_impact_totals
from sentinel.shared.authz import Permission, Principal, require
from sentinel.shared.errors import not_found
from sentinel.validation.engine import RunOutcome
from sentinel.validation.rules import (
    MONEY,
    RunContext,
    arithmetic_difference,
    cell,
    in_table,
    rows_alias,
    typed,
)
from sentinel.validation.tables import finding_records, findings, validation_runs

CONFIRMED, POTENTIAL = "CONFIRMED_DISCREPANCY", "POTENTIAL_EXPOSURE"
# Columns the provisional KPI definitions read (PRD §12.3). Absent columns read as NULL.
STATUS, DOCUMENT_TYPE, INVOICE_DATE = "status", "document_type", "invoice_date"
ZERO = Decimal("0.00")
MAX_PCT = Decimal("9999999.99")
RANKING_LIMIT = 50

FIGURE_ASSUMPTIONS = {
    "non_canonical_gross": "Gross amount of the duplicate copies. The first occurrence is kept "
    "by convention; this does not say which record is genuine.",
    "abs_difference": "Absolute difference between the stated gross amount and net plus tax.",
    "gross": "Gross amount of the affected records. Their correct treatment cannot be determined.",
    "abs_gross": "Absolute gross amount of the affected records. The sign error is proven; the "
    "correct document type or amount is not.",
    "count_only": "Value not quantifiable: the amount cannot be parsed.",
}
ASSUME_DUPLICATES = "Duplicate copies removed; the first occurrence is kept by convention."
ASSUME_SHARED_ID = "Rows sharing an ID counted once (first occurrence)."
ASSUME_ALL_CONFIRMED = "All confirmed duplicate copies removed; the first occurrence is kept."
ASSUME_NO_PERIOD_FILTER = "A report without a period filter would include these invoices."
ASSUME_UNATTRIBUTED = "Spend is real but cannot be attributed to a supplier."
ASSUME_UNKNOWN = "Correct treatment unknown."


def money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _impacted(outcome: RunOutcome) -> list[tuple[Rule, UUID]]:
    return [
        (rule, outcome.findings[rule.id])
        for rule in sorted(outcome.rules.rules, key=lambda r: r.id)
        if rule.id in outcome.findings and rule.table == outcome.ctx.contract.money_table
    ]


def _supplier_link(contract: Contract) -> tuple[str, str, str] | None:
    """(column, ref_table, ref_column) of the money table's first relationship, if any."""
    for rel in contract.relationships:
        table, _, column = rel.source.partition(".")
        if table == contract.money_table:
            ref_table, _, ref_column = rel.target.partition(".")
            return column, ref_table, ref_column
    return None


def _members(rule: Rule, finding_id: UUID) -> Any:
    """Row numbers that contribute to a finding's figure (non-canonical only for duplicates)."""
    query = select(finding_records.c.row_num).where(finding_records.c.finding_id == finding_id)
    if rule.impact.basis == "non_canonical_gross":
        query = query.where(finding_records.c.is_canonical.is_(False))
    return query


# ---- per-finding figures (FS §5.2) -----------------------------------------------------------
def _figures(conn: Connection, outcome: RunOutcome) -> None:
    ctx, contract = outcome.ctx, outcome.ctx.contract
    link = _supplier_link(contract)
    for rule, finding_id in _impacted(outcome):
        if rule.impact.category is None:
            continue
        basis = rule.impact.basis
        r = rows_alias()
        gross = typed(cell(r, contract.amount_column), "decimal")
        if basis == "abs_difference":
            params = rule.parsed
            assert isinstance(params, m.ArithmeticCheckParams)
            amount = arithmetic_difference(r, params)
        elif basis == "abs_gross":
            amount = func.abs(gross)
        elif basis == "count_only":
            amount = cast(sql_null(), MONEY)
        else:
            amount = gross
        members = _members(rule, finding_id).subquery("mem")
        valued = (
            select(
                func.coalesce(cell(r, contract.currency_column), "").label("currency"),
                amount.label("amount"),
                (cell(r, link[0]) if link else cast(sql_null(), Text)).label("supplier"),
            )
            .select_from(
                members.join(r, in_table(r, ctx, rule.table) & (r.c.row_num == members.c.row_num))
            )
            .subquery("val")
        )
        rows = conn.execute(
            select(
                valued.c.currency,
                func.coalesce(func.sum(valued.c.amount), 0).label("amount"),
                func.count().label("records"),
                func.count().filter(valued.c.amount.is_(None)).label("unquantifiable"),
                func.count(func.distinct(valued.c.supplier)).label("suppliers"),
            )
            .group_by(valued.c.currency)
            .order_by(valued.c.currency.collate("C"))
        ).all()
        quantifiable = basis != "count_only"
        for row in rows:
            conn.execute(
                insert(impact_figures).values(
                    finding_id=finding_id,
                    category=rule.impact.category,
                    currency=row.currency,
                    amount=row.amount if quantifiable else None,
                    quantifiable=quantifiable,
                    record_count=row.records,
                    formula_id=basis,
                    assumption=FIGURE_ASSUMPTIONS[basis],
                    inputs={
                        "amount_column": contract.amount_column,
                        "unquantifiable_count": row.unquantifiable if quantifiable else row.records,
                        "supplier_count": row.suppliers,
                        "key_list_truncated": rule.id in outcome.truncated,
                    },
                )
            )


# ---- version totals, overlap-aware (FS §5.3) -------------------------------------------------
def _totals(conn: Connection, outcome: RunOutcome) -> None:
    ctx, contract = outcome.ctx, outcome.ctx.contract
    r = rows_alias()
    gross = typed(cell(r, contract.amount_column), "decimal")
    amounts = [gross]  # kind 0 = the whole gross amount; kind i = the i-th arithmetic difference
    confirmed, potential = [], []
    for rule, finding_id in _impacted(outcome):
        members = _members(rule, finding_id)
        if rule.impact.category == CONFIRMED:
            kind = 0
            if rule.impact.basis == "abs_difference":
                params = rule.parsed
                assert isinstance(params, m.ArithmeticCheckParams)
                amounts.append(arithmetic_difference(r, params))
                kind = len(amounts) - 1
            confirmed.append(
                select(members.subquery().c.row_num, literal(kind, Integer).label("kind"))
            )
        elif rule.impact.category == POTENTIAL:
            potential.append(select(members.subquery().c.row_num))
    if not confirmed and not potential:
        return

    empty = select(cast(sql_null(), Integer).label("row_num"), literal(0, Integer).label("kind"))
    all_confirmed = union_all(*(confirmed or [empty.where(literal(False))])).subquery("c_all")
    # A record counts once: at its gross amount if it is a duplicate copy, else its difference.
    c_rows = (
        select(all_confirmed.c.row_num, func.min(all_confirmed.c.kind).label("kind"))
        .group_by(all_confirmed.c.row_num)
        .subquery("c")
    )
    parts = [select(literal(CONFIRMED).label("category"), c_rows.c.row_num, c_rows.c.kind)]
    if potential:
        all_potential = union_all(*potential).subquery("p_all")
        # Confirmed takes precedence: its keys are removed from potential exposure.
        p_rows = (
            select(all_potential.c.row_num)
            .where(all_potential.c.row_num.not_in(select(c_rows.c.row_num)))
            .distinct()
            .subquery("p")
        )
        parts.append(
            select(literal(POTENTIAL).label("category"), p_rows.c.row_num, literal(0, Integer))
        )
    members = union_all(*parts).subquery("mem")
    valued = (
        select(
            members.c.category,
            func.coalesce(cell(r, contract.currency_column), "").label("currency"),
            case(*[(members.c.kind == i, a) for i, a in enumerate(amounts)]).label("amount"),
        )
        .select_from(
            members.join(
                r, in_table(r, ctx, contract.money_table) & (r.c.row_num == members.c.row_num)
            )
        )
        .subquery("val")
    )
    conn.execute(
        insert(run_impact_totals).from_select(
            ["run_id", "category", "currency", "amount", "record_count", "unquantifiable_count"],
            select(
                literal(outcome.run_id),
                valued.c.category,
                valued.c.currency,
                func.coalesce(func.sum(valued.c.amount), 0),
                func.count(),
                func.count().filter(valued.c.amount.is_(None)),
            ).group_by(valued.c.category, valued.c.currency),
        )
    )


# ---- KPIs (FS §5.4, PRD §12.3; provisional) --------------------------------------------------
KpiKey = tuple[str, str, str | None]  # (kpi_id, currency, supplier_id)


def _kpi_tables(
    conn: Connection, ctx: RunContext, excluded: list[UUID]
) -> tuple[dict[KpiKey, Decimal], dict[KpiKey, Decimal]]:
    """KPI-01 to KPI-04 as reported, and again with the given findings' duplicate copies
    excluded. Both use one definition and one period filter, so a delta reflects only the
    excluded records (FR-012.1)."""
    contract = ctx.contract
    r = rows_alias()
    link = _supplier_link(contract)
    supplier: Any
    if link is not None:
        ref = rows_alias("ref")
        known = exists().where(in_table(ref, ctx, link[1]), cell(ref, link[2]) == cell(r, link[0]))
        supplier = case((known, cell(r, link[0])), else_=None)
    else:
        supplier = cast(sql_null(), Text)
    is_excluded = exists().where(
        finding_records.c.finding_id.in_(excluded),
        finding_records.c.is_canonical.is_(False),
        finding_records.c.row_num == r.c.row_num,
    )
    included = (
        select(
            func.coalesce(cell(r, contract.currency_column), "").label("currency"),
            supplier.label("supplier_id"),
            typed(cell(r, contract.amount_column), "decimal").label("amount"),
            func.coalesce(cell(r, DOCUMENT_TYPE) == "INVOICE", False).label("is_invoice"),
            (is_excluded if excluded else literal(False)).label("excluded"),
        )
        .where(
            in_table(r, ctx, contract.money_table),
            cell(r, STATUS).is_distinct_from("CANCELLED"),
            typed(cell(r, INVOICE_DATE), "date").between(ctx.period_start, ctx.period_end),
        )
        .subquery("i")
    )
    kept = ~included.c.excluded
    rows = conn.execute(
        select(
            included.c.currency,
            included.c.supplier_id,
            func.coalesce(func.sum(included.c.amount), 0).label("spend"),
            func.coalesce(func.sum(included.c.amount).filter(kept), 0).label("spend_kept"),
            func.count().filter(included.c.is_invoice).label("invoices"),
            func.count().filter(included.c.is_invoice, kept).label("invoices_kept"),
        ).group_by(included.c.currency, included.c.supplier_id)
    ).all()

    reported: dict[KpiKey, Decimal] = defaultdict(lambda: ZERO)
    adjusted: dict[KpiKey, Decimal] = defaultdict(lambda: ZERO)
    for row in rows:
        for table, spend, count in (
            (reported, row.spend, row.invoices),
            (adjusted, row.spend_kept, row.invoices_kept),
        ):
            table[("KPI-01", row.currency, None)] += spend
            table[("KPI-03", row.currency, None)] += Decimal(count)
            table[("KPI-04", row.currency, None)] += ZERO if row.supplier_id is not None else spend
            if row.supplier_id is not None:
                table[("KPI-02", row.currency, row.supplier_id)] += spend
    return dict(reported), dict(adjusted)


def _delta(reported: Decimal, adjusted: Decimal) -> tuple[Decimal, Decimal | None, str]:
    """Absolute delta, percentage of the as-reported value (ROUND_HALF_EVEN) and direction."""
    delta = abs(reported - adjusted)
    pct = None
    if reported != 0:
        pct = (delta / abs(reported) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        pct = pct if pct <= MAX_PCT else None
    direction = "NONE" if delta == 0 else "OVERSTATED" if reported > adjusted else "UNDERSTATED"
    return delta, pct, direction


def _kpi_row(
    run_id: UUID, key: KpiKey, scope: str, value: Decimal, *, finding_id: UUID | None = None,
    reported: Decimal | None = None, assumption: str | None = None, direction: str | None = None,
    delta: Decimal | None = None,
) -> dict[str, Any]:  # fmt: skip
    row: dict[str, Any] = {
        "run_id": run_id, "kpi_id": key[0], "scope": scope, "finding_id": finding_id,
        "currency": key[1], "supplier_id": key[2], "value": value, "delta_abs": delta,
        "delta_pct": None, "direction": direction, "assumption": assumption,
    }  # fmt: skip
    if reported is not None and direction is None:
        row["delta_abs"], row["delta_pct"], row["direction"] = _delta(reported, value)
    return row


def _kpis(conn: Connection, outcome: RunOutcome) -> None:
    ctx, run_id = outcome.ctx, outcome.run_id
    impacted = _impacted(outcome)
    confirmed_duplicates = [
        fid for rule, fid in impacted
        if rule.impact.category == CONFIRMED and rule.impact.basis == "non_canonical_gross"
    ]  # fmt: skip
    reported, adjusted = _kpi_tables(conn, ctx, confirmed_duplicates)
    rows = [_kpi_row(run_id, key, "AS_REPORTED", value) for key, value in reported.items()]
    rows += [
        _kpi_row(run_id, key, "FULLY_ADJUSTED", adjusted[key], reported=value,
                 assumption=ASSUME_ALL_CONFIRMED)
        for key, value in reported.items()
    ]  # fmt: skip

    currencies = sorted({key[1] for key in reported})
    for rule, finding_id in impacted:
        if not rule.kpis:
            continue
        if rule.impact.basis == "non_canonical_gross":
            _, without = _kpi_tables(conn, ctx, [finding_id])
            text = ASSUME_DUPLICATES if rule.impact.category == CONFIRMED else ASSUME_SHARED_ID
            for key, value in reported.items():
                # Per-supplier rows are kept only where the issue changes the supplier's spend.
                if key[0] in rule.kpis and (key[2] is None or without[key] != value):
                    rows.append(
                        _kpi_row(run_id, key, "ISSUE", without[key], finding_id=finding_id,
                                 reported=value, assumption=text)
                    )  # fmt: skip
            continue
        params = rule.parsed
        if isinstance(params, m.DateWindowParams) and params.window == "period":
            # Already outside the KPI period filter. The figure is what a report without that
            # filter would add to KPI-01 (FS §5.4).
            r = rows_alias()
            valued = (
                select(
                    func.coalesce(cell(r, ctx.contract.currency_column), "").label("currency"),
                    typed(cell(r, ctx.contract.amount_column), "decimal").label("amount"),
                )
                .select_from(
                    finding_records.join(
                        r, in_table(r, ctx, rule.table) & (r.c.row_num == finding_records.c.row_num)
                    )
                )
                .where(finding_records.c.finding_id == finding_id)
                .subquery("val")
            )
            for row in conn.execute(
                select(
                    valued.c.currency,
                    func.coalesce(func.sum(valued.c.amount), 0).label("amount"),
                )
                .group_by(valued.c.currency)
            ):  # fmt: skip
                key = ("KPI-01", row.currency, None)
                rows.append(
                    _kpi_row(run_id, key, "ISSUE", reported.get(key, ZERO), finding_id=finding_id,
                             assumption=ASSUME_NO_PERIOD_FILTER, direction="OVERSTATED",
                             delta=abs(row.amount))
                )  # fmt: skip
            continue
        unattributed = "KPI-04" in rule.kpis and rule.impact.basis == "gross"
        for kpi in rule.kpis:
            for currency in currencies:
                if kpi == "KPI-02":
                    value = sum(
                        (v for k, v in reported.items() if k[0] == kpi and k[1] == currency), ZERO
                    )
                else:
                    value = reported.get((kpi, currency, None), ZERO)
                rows.append(
                    _kpi_row(run_id, (kpi, currency, None), "ISSUE", value, finding_id=finding_id,
                             assumption=ASSUME_UNATTRIBUTED if unattributed else ASSUME_UNKNOWN,
                             direction="INDETERMINATE")
                )  # fmt: skip
    if rows:
        conn.execute(insert(kpi_values), rows)


def compute(conn: Connection, outcome: RunOutcome) -> None:
    """Post-step of a validation run: figures, version totals and KPI values."""
    _figures(conn, outcome)
    _totals(conn, outcome)
    _kpis(conn, outcome)


# ---- queries -----------------------------------------------------------------------------
def _kpi_view(row: Any) -> dict[str, Any]:
    return {
        "kpi_id": row.kpi_id,
        "currency": row.currency,
        "supplier_id": row.supplier_id,
        "value": money(row.value),
        "delta_abs": money(row.delta_abs),
        "delta_pct": money(row.delta_pct),
        "direction": row.direction,
        "assumption": row.assumption,
    }


def run_impact(principal: Principal, conn: Connection, run_id: UUID) -> dict[str, Any]:
    """Version totals by category and currency, the KPI table and the supplier ranking."""
    require(principal, Permission.READ)
    if (
        conn.execute(select(validation_runs.c.id).where(validation_runs.c.id == run_id)).first()
        is None
    ):
        raise not_found("Validation run")
    totals = conn.execute(
        select(run_impact_totals)
        .where(run_impact_totals.c.run_id == run_id)
        .order_by(run_impact_totals.c.category, run_impact_totals.c.currency.collate("C"))
    ).all()
    values = conn.execute(
        select(kpi_values)
        .where(kpi_values.c.run_id == run_id, kpi_values.c.scope != "ISSUE")
        .order_by(
            kpi_values.c.kpi_id,
            kpi_values.c.currency.collate("C"),
            kpi_values.c.supplier_id.collate("C"),
        )
    ).all()
    reported = {
        (v.kpi_id, v.currency, v.supplier_id): v.value for v in values if v.scope == "AS_REPORTED"
    }
    table = [
        {
            **_kpi_view(v),
            "as_reported": money(reported[(v.kpi_id, v.currency, v.supplier_id)]),
            "fully_adjusted": money(v.value),
        }
        for v in values
        if v.scope == "FULLY_ADJUSTED"
    ]
    for item in table:
        del item["value"]
    changed = [k for k in table if k["kpi_id"] == "KPI-02" and k["direction"] != "NONE"]
    changed.sort(key=lambda k: (-Decimal(k["delta_abs"]), k["currency"], k["supplier_id"]))
    return {
        "totals": [
            {
                "category": t.category,
                "currency": t.currency,
                "amount": money(t.amount),
                "record_count": t.record_count,
                "unquantifiable_count": t.unquantifiable_count,
            }
            for t in totals
        ],
        "kpis": [k for k in table if k["kpi_id"] != "KPI-02"],
        "supplier_ranking": changed[:RANKING_LIMIT],
        "supplier_ranking_total": len(changed),
    }


def finding_impact(principal: Principal, conn: Connection, finding_id: UUID) -> dict[str, Any]:
    """One finding's impact figures with their evidence, and its KPI effects (FR-011, FR-012)."""
    require(principal, Permission.READ)
    if conn.execute(select(findings.c.id).where(findings.c.id == finding_id)).first() is None:
        raise not_found("Finding")
    figures = conn.execute(
        select(impact_figures)
        .where(impact_figures.c.finding_id == finding_id)
        .order_by(impact_figures.c.category, impact_figures.c.currency.collate("C"))
    ).all()
    effects = conn.execute(
        select(kpi_values)
        .where(kpi_values.c.finding_id == finding_id)
        .order_by(
            kpi_values.c.kpi_id,
            kpi_values.c.currency.collate("C"),
            kpi_values.c.supplier_id.collate("C"),
        )
    ).all()
    return {
        "figures": [
            {
                "category": f.category,
                "currency": f.currency,
                "amount": money(f.amount),
                "quantifiable": f.quantifiable,
                "record_count": f.record_count,
                "formula_id": f.formula_id,
                "assumption": f.assumption,
                "inputs": f.inputs,
            }
            for f in figures
        ],
        "kpi_effects": [_kpi_view(e) for e in effects],
    }
