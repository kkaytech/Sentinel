"""Validation runs, findings and finding records (Doc 4 §4.6, FR-006 to FR-009).

Revision ID: 0006
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

RUN_CHILDREN = (("app.findings", "run"), ("app.finding_records", "finding"))


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.validation_runs (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            dataset_version_id  uuid NOT NULL REFERENCES app.dataset_versions (id),
            rule_set_version_id uuid NOT NULL REFERENCES app.config_versions (id),
            engine_version      text NOT NULL,
            period              char(7) NOT NULL,
            reference_date      date NOT NULL,
            status              text NOT NULL DEFAULT 'RUNNING'
                                CHECK (status IN ('RUNNING', 'COMPLETED', 'ERROR')),
            triggered_by        uuid NOT NULL REFERENCES app.users (id),
            started_at          timestamptz NOT NULL DEFAULT clock_timestamp(),
            finished_at         timestamptz NULL,
            finding_counts      jsonb NULL,
            not_evaluated       jsonb NULL,
            error_detail        jsonb NULL,
            CHECK ((status = 'RUNNING') = (finished_at IS NULL))
        )
        """
    )
    # One run in progress per version (NFR-001).
    op.execute(
        "CREATE UNIQUE INDEX validation_runs_one_running_uq ON app.validation_runs "
        "(dataset_version_id) WHERE status = 'RUNNING'"
    )
    op.execute(
        "CREATE INDEX validation_runs_version_idx ON app.validation_runs "
        "(dataset_version_id, started_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE app.findings (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id          uuid NOT NULL REFERENCES app.validation_runs (id),
            rule_id         text NOT NULL,
            rule_type       text NOT NULL,
            severity        text NOT NULL CHECK (severity IN ('BLOCKING', 'WARNING', 'INFO')),
            waivable        boolean NOT NULL,
            table_name      text NOT NULL,
            columns         text[] NOT NULL,
            failing_count   int NOT NULL CHECK (failing_count > 0),
            evaluated_count int NOT NULL,
            truncated       boolean NOT NULL,
            samples         jsonb NOT NULL,
            message         text NOT NULL,
            details         jsonb NOT NULL DEFAULT '{}'::jsonb,
            UNIQUE (run_id, rule_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.finding_records (
            finding_id   uuid NOT NULL REFERENCES app.findings (id),
            ordinal      int NOT NULL,
            row_num      int NOT NULL,
            record_key   text NOT NULL,
            group_no     int NULL,
            is_canonical boolean NULL,
            PRIMARY KEY (finding_id, ordinal)
        )
        """
    )
    op.execute("CREATE INDEX finding_records_row_idx ON app.finding_records (finding_id, row_num)")

    op.execute(
        "GRANT SELECT, INSERT ON app.validation_runs, app.findings, app.finding_records "
        "TO sentinel_app"
    )
    op.execute(
        "GRANT UPDATE (status, finished_at, finding_counts, not_evaluated, error_detail) "
        "ON app.validation_runs TO sentinel_app"
    )

    # A run moves once, RUNNING -> COMPLETED or ERROR. Terminal runs never change (FS §2.2).
    op.execute(
        """
        CREATE FUNCTION app.sentinel_run_transition() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF current_user = 'sentinel_owner' THEN
                RETURN NEW;
            END IF;
            IF OLD.status <> 'RUNNING' OR NEW.status NOT IN ('COMPLETED', 'ERROR') THEN
                RAISE EXCEPTION 'sentinel: validation run status % -> % is not permitted',
                    OLD.status, NEW.status USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    # Open-parent guard (Doc 4 §4.10): children can be added only while their run is RUNNING.
    # TG_ARGV[0] says how to reach the run: directly ('run') or through the finding.
    op.execute(
        """
        CREATE FUNCTION app.sentinel_open_parent_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            run_status text;
        BEGIN
            IF TG_ARGV[0] = 'finding' THEN
                SELECT r.status INTO run_status
                FROM app.findings f JOIN app.validation_runs r ON r.id = f.run_id
                WHERE f.id = NEW.finding_id;
            ELSE
                SELECT status INTO run_status FROM app.validation_runs WHERE id = NEW.run_id;
            END IF;
            IF run_status IS DISTINCT FROM 'RUNNING' THEN
                RAISE EXCEPTION 'sentinel: the validation run is sealed; % cannot be added to',
                    TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    for fn in ("sentinel_run_transition", "sentinel_open_parent_guard"):
        op.execute(f"REVOKE ALL ON FUNCTION app.{fn}() FROM PUBLIC")

    op.execute(
        "CREATE TRIGGER validation_runs_transition BEFORE UPDATE ON app.validation_runs "
        "FOR EACH ROW EXECUTE FUNCTION app.sentinel_run_transition()"
    )
    op.execute(
        "CREATE TRIGGER validation_runs_limit_update BEFORE UPDATE ON app.validation_runs "
        "FOR EACH ROW EXECUTE FUNCTION app.sentinel_limit_update("
        "'status', 'finished_at', 'finding_counts', 'not_evaluated', 'error_detail')"
    )
    for when, scope in (("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")):
        op.execute(
            f"CREATE TRIGGER validation_runs_forbid_{when.lower()} BEFORE {when} "
            f"ON app.validation_runs FOR EACH {scope} "
            "EXECUTE FUNCTION app.sentinel_forbid_change()"
        )
    for table, parent in RUN_CHILDREN:
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
