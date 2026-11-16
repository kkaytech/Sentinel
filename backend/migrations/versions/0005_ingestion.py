"""Ingestion and version data (Doc 4 §4.5, FR-003, FR-004; ADR-006 variant A).

Revision ID: 0005
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _forbid(table: str, *operations: str) -> None:
    name = table.split(".")[1]
    for operation in operations:
        scope = "STATEMENT" if operation == "TRUNCATE" else "ROW"
        op.execute(
            f"CREATE TRIGGER {name}_forbid_{operation.lower()} BEFORE {operation} ON {table} "
            f"FOR EACH {scope} EXECUTE FUNCTION app.sentinel_forbid_change()"
        )


def _seal(table: str, parent: str, column: str) -> None:
    name = table.split(".")[1]
    op.execute(
        f"CREATE TRIGGER {name}_seal BEFORE INSERT ON {table} FOR EACH ROW "
        f"EXECUTE FUNCTION app.sentinel_seal_guard('{parent}', '{column}')"
    )


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE app.dataset_periods (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            dataset_key      text NOT NULL,
            period           char(7) NOT NULL CHECK (period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
            created_at       timestamptz NOT NULL DEFAULT now(),
            last_activity_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (dataset_key, period)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.dataset_versions (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            dataset_period_id   uuid NOT NULL REFERENCES app.dataset_periods (id),
            seq                 int NOT NULL CHECK (seq > 0),
            label               text NOT NULL UNIQUE,
            contract_version_id uuid NOT NULL REFERENCES app.config_versions (id),
            content_hash        char(64) NOT NULL,
            hash_algorithm      text NOT NULL,
            columns             jsonb NOT NULL,
            row_counts          jsonb NOT NULL,
            status              text NOT NULL DEFAULT 'ACTIVE'
                                CHECK (status IN ('ACTIVE', 'SUPERSEDED')),
            created_by          uuid NOT NULL REFERENCES app.users (id),
            created_at          timestamptz NOT NULL DEFAULT now(),
            creating_xact       xid8 NOT NULL DEFAULT pg_current_xact_id(),
            UNIQUE (dataset_period_id, seq)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX dataset_versions_one_active_uq ON app.dataset_versions "
        "(dataset_period_id) WHERE status = 'ACTIVE'"
    )
    op.execute(
        """
        CREATE TABLE app.ingestion_attempts (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            dataset_period_id  uuid NOT NULL REFERENCES app.dataset_periods (id),
            status             text NOT NULL
                               CHECK (status IN ('SUCCEEDED', 'FAILED', 'DUPLICATE_CONTENT')),
            initiated_by       uuid NOT NULL REFERENCES app.users (id),
            started_at         timestamptz NOT NULL,
            finished_at        timestamptz NOT NULL DEFAULT now(),
            files              jsonb NOT NULL,
            errors             jsonb NULL,
            dataset_version_id uuid NULL REFERENCES app.dataset_versions (id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ingestion_attempts_period_idx ON app.ingestion_attempts "
        "(dataset_period_id, started_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE data.raw_files (
            dataset_version_id uuid NOT NULL REFERENCES app.dataset_versions (id),
            table_name         text NOT NULL,
            filename           text NOT NULL,
            sha256             char(64) NOT NULL,
            size_bytes         int NOT NULL,
            bytes              bytea NOT NULL,
            PRIMARY KEY (dataset_version_id, table_name)
        )
        """
    )
    # ADR-006 variant A (accepted after PoC-1): raw text cells, primary key index only.
    op.execute(
        """
        CREATE TABLE data.version_rows (
            dataset_version_id uuid NOT NULL REFERENCES app.dataset_versions (id),
            table_name         text NOT NULL,
            row_num            int NOT NULL CHECK (row_num > 0),
            cells              jsonb NOT NULL,
            PRIMARY KEY (dataset_version_id, table_name, row_num)
        )
        """
    )
    # FR-005 (Should Have, M3). The table exists now so the 0005 shape matches Doc 4.
    op.execute(
        """
        CREATE TABLE app.column_profiles (
            dataset_version_id uuid NOT NULL REFERENCES app.dataset_versions (id),
            table_name         text NOT NULL,
            column_name        text NOT NULL,
            stats              jsonb NOT NULL,
            PRIMARY KEY (dataset_version_id, table_name, column_name)
        )
        """
    )
    op.execute(
        "ALTER TABLE audit.events ADD CONSTRAINT events_dataset_version_fk "
        "FOREIGN KEY (dataset_version_id) REFERENCES app.dataset_versions (id)"
    )

    op.execute(
        "GRANT SELECT, INSERT ON app.dataset_periods, app.dataset_versions, "
        "app.ingestion_attempts, app.column_profiles, data.raw_files, data.version_rows "
        "TO sentinel_app"
    )
    op.execute("GRANT UPDATE (last_activity_at) ON app.dataset_periods TO sentinel_app")
    op.execute("GRANT UPDATE (status) ON app.dataset_versions TO sentinel_app")

    # A version only ever moves ACTIVE -> SUPERSEDED (FS §2.1).
    op.execute(
        """
        CREATE FUNCTION app.sentinel_version_transition() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.status IS DISTINCT FROM OLD.status
               AND NOT (OLD.status = 'ACTIVE' AND NEW.status = 'SUPERSEDED') THEN
                RAISE EXCEPTION 'sentinel: dataset version status % -> % is not permitted',
                    OLD.status, NEW.status USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.sentinel_version_transition() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER dataset_versions_transition BEFORE UPDATE ON app.dataset_versions "
        "FOR EACH ROW EXECUTE FUNCTION app.sentinel_version_transition()"
    )
    for table, column in (
        ("app.dataset_periods", "last_activity_at"),
        ("app.dataset_versions", "status"),
    ):
        name = table.split(".")[1]
        op.execute(
            f"CREATE TRIGGER {name}_limit_update BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION app.sentinel_limit_update('{column}')"
        )
        _forbid(table, "DELETE", "TRUNCATE")
    for table in (
        "app.ingestion_attempts",
        "app.column_profiles",
        "data.raw_files",
        "data.version_rows",
    ):
        _forbid(table, "UPDATE", "DELETE", "TRUNCATE")
    for table in ("app.column_profiles", "data.raw_files", "data.version_rows"):
        _seal(table, "app.dataset_versions", "dataset_version_id")


def downgrade() -> None:
    raise NotImplementedError("Sentinel migrations are forward-only")
