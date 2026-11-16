"""Publications, attempts and the typed published snapshot (Doc 4 §4.9, PUB-001 to PUB-006).

The job queue that Doc 4 also places in 0009 is not created here: validation runs still
execute within the request. It will arrive as its own migration.

Revision ID: 0009
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

IMMUTABLE = (
    "app.publications",
    "app.publication_attempts",
    "published.suppliers",
    "published.invoices",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.publications (
            id                   uuid PRIMARY KEY,
            publication_ref      text NOT NULL UNIQUE,
            dataset_period_id    uuid NOT NULL UNIQUE REFERENCES app.dataset_periods (id),
            dataset_key          text NOT NULL,
            period               char(7) NOT NULL,
            dataset_version_id   uuid NOT NULL REFERENCES app.dataset_versions (id),
            content_hash         char(64) NOT NULL,
            validation_run_id    uuid NOT NULL REFERENCES app.validation_runs (id),
            rule_set_version_id  uuid NOT NULL REFERENCES app.config_versions (id),
            approval_decision_id uuid NOT NULL REFERENCES app.approval_decisions (id),
            published_by         uuid NOT NULL REFERENCES app.users (id),
            published_at         timestamptz NOT NULL,
            status               text NOT NULL DEFAULT 'CURRENT' CHECK (status IN ('CURRENT')),
            snapshot_format      text NOT NULL,
            snapshot_hash        char(64) NOT NULL,
            table_hashes         jsonb NOT NULL,
            row_counts           jsonb NOT NULL,
            manifest_bytes       bytea NOT NULL,
            manifest_sha256      char(64) NOT NULL,
            creating_xact        xid8 NOT NULL DEFAULT pg_current_xact_id()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE app.publication_attempts (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            dataset_version_id uuid NOT NULL REFERENCES app.dataset_versions (id),
            attempted_by       uuid NOT NULL REFERENCES app.users (id),
            attempted_at       timestamptz NOT NULL DEFAULT now(),
            outcome            text NOT NULL CHECK (outcome IN ('SUCCEEDED', 'FAILED')),
            checks             jsonb NOT NULL,
            publication_id     uuid NULL REFERENCES app.publications (id)
        )
        """
    )
    op.execute(
        "CREATE INDEX publication_attempts_version_idx ON app.publication_attempts "
        "(dataset_version_id, attempted_at)"
    )
    op.execute(
        """
        CREATE TABLE published.suppliers (
            publication_id   uuid NOT NULL REFERENCES app.publications (id),
            supplier_id      text NOT NULL,
            supplier_name    text NULL,
            country_code     text NULL,
            default_currency text NULL,
            status           text NULL,
            active_from      date NULL,
            active_to        date NULL,
            tax_id           text NULL,
            PRIMARY KEY (publication_id, supplier_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE published.invoices (
            publication_id          uuid NOT NULL REFERENCES app.publications (id),
            invoice_id              text NOT NULL,
            supplier_id             text NULL,
            supplier_invoice_number text NULL,
            document_type           text NULL,
            invoice_date            date NULL,
            due_date                date NULL,
            currency                text NOT NULL,
            net_amount              numeric(18,2) NULL,
            tax_amount              numeric(18,2) NULL,
            gross_amount            numeric(18,2) NOT NULL,
            status                  text NULL,
            description             text NULL,
            PRIMARY KEY (publication_id, invoice_id)
        )
        """
    )
    op.execute(f"GRANT SELECT, INSERT ON {', '.join(IMMUTABLE)} TO sentinel_app")
    for table in IMMUTABLE:
        name = table.replace(".", "_")
        for operation in ("UPDATE", "DELETE", "TRUNCATE"):
            scope = "STATEMENT" if operation == "TRUNCATE" else "ROW"
            op.execute(
                f"CREATE TRIGGER {name}_forbid_{operation.lower()} BEFORE {operation} ON {table} "
                f"FOR EACH {scope} EXECUTE FUNCTION app.sentinel_forbid_change()"
            )
    for table in ("published.suppliers", "published.invoices"):
        name = table.replace(".", "_")
        op.execute(
            f"CREATE TRIGGER {name}_seal BEFORE INSERT ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION app.sentinel_seal_guard('app.publications', 'publication_id')"
        )

    # Database backstop (ARD §7.3.4): a publication needs an APPROVE decision bound to the
    # same tuple, made by someone other than the submitter. Independent of the service code.
    op.execute(
        """
        CREATE FUNCTION app.sentinel_publication_backstop() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            ok boolean;
        BEGIN
            SELECT d.decision = 'APPROVE'
                   AND d.decided_by <> r.submitted_by
                   AND d.dataset_version_id = NEW.dataset_version_id
                   AND d.content_hash = NEW.content_hash
                   AND d.validation_run_id = NEW.validation_run_id
                   AND d.rule_set_version_id = NEW.rule_set_version_id
              INTO ok
              FROM app.approval_decisions d
              JOIN app.review_requests r ON r.id = d.review_request_id
             WHERE d.id = NEW.approval_decision_id;
            IF ok IS NOT TRUE THEN
                RAISE EXCEPTION 'sentinel: publication refused: no matching approval by a '
                                'different user for this exact data and validation'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.sentinel_publication_backstop() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER publications_backstop BEFORE INSERT ON app.publications "
        "FOR EACH ROW EXECUTE FUNCTION app.sentinel_publication_backstop()"
    )


def downgrade() -> None:
    raise NotImplementedError("Sentinel migrations are forward-only")
