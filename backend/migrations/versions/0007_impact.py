"""Impact figures, run totals and KPI values (Doc 4 §4.7, FR-011, FR-012).

Currency columns are text, not char(3): impact is grouped by the raw currency cell, so an
invalid code of any length must be storable (decided after PoC-1). No column is named with
the word "loss" (BR-007.2).

Revision ID: 0007
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TABLES = (
    ("app.impact_figures", "finding"),
    ("app.run_impact_totals", "run"),
    ("app.kpi_values", "run"),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.impact_figures (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            finding_id   uuid NOT NULL REFERENCES app.findings (id),
            category     text NOT NULL
                         CHECK (category IN ('CONFIRMED_DISCREPANCY', 'POTENTIAL_EXPOSURE')),
            currency     text NULL,
            amount       numeric(18,2) NULL,
            quantifiable boolean NOT NULL,
            record_count int NOT NULL,
            formula_id   text NOT NULL,
            assumption   text NOT NULL,
            inputs       jsonb NOT NULL,
            CHECK (quantifiable = (amount IS NOT NULL))
        )
        """
    )
    op.execute("CREATE INDEX impact_figures_finding_idx ON app.impact_figures (finding_id)")
    op.execute(
        """
        CREATE TABLE app.run_impact_totals (
            run_id               uuid NOT NULL REFERENCES app.validation_runs (id),
            category             text NOT NULL CHECK (
                category IN ('CONFIRMED_DISCREPANCY', 'POTENTIAL_EXPOSURE')
            ),
            currency             text NOT NULL,
            amount               numeric(18,2) NOT NULL,
            record_count         int NOT NULL,
            unquantifiable_count int NOT NULL,
            PRIMARY KEY (run_id, category, currency)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.kpi_values (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id      uuid NOT NULL REFERENCES app.validation_runs (id),
            kpi_id      text NOT NULL,
            scope       text NOT NULL CHECK (scope IN ('AS_REPORTED', 'ISSUE', 'FULLY_ADJUSTED')),
            finding_id  uuid NULL REFERENCES app.findings (id),
            currency    text NOT NULL,
            supplier_id text NULL,
            value       numeric(20,2) NOT NULL,
            delta_abs   numeric(20,2) NULL,
            delta_pct   numeric(9,2) NULL,
            direction   text NULL
                        CHECK (direction IN ('OVERSTATED', 'UNDERSTATED', 'INDETERMINATE', 'NONE')),
            assumption  text NULL,
            CHECK ((scope = 'ISSUE') = (finding_id IS NOT NULL))
        )
        """
    )
    op.execute("CREATE INDEX kpi_values_run_idx ON app.kpi_values (run_id, kpi_id, scope)")
    op.execute(
        "GRANT SELECT, INSERT ON app.impact_figures, app.run_impact_totals, app.kpi_values "
        "TO sentinel_app"
    )
    for table, parent in TABLES:
        name = table.split(".")[1]
        op.execute(
            f"CREATE TRIGGER {name}_open_parent BEFORE INSERT ON {table} FOR EACH ROW "
            f"EXECUTE FUNCTION app.sentinel_open_parent_guard('{parent}')"
        )
        for when, scope in (("UPDATE", "ROW"), ("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")):
            op.execute(
                f"CREATE TRIGGER {name}_forbid_{when.lower()} BEFORE {when} ON {table} "
                f"FOR EACH {scope} EXECUTE FUNCTION app.sentinel_forbid_change()"
            )


def downgrade() -> None:
    raise NotImplementedError("Sentinel migrations are forward-only")
