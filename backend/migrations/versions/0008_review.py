"""Issues, notes, waivers, review requests and approvals (Doc 4 §4.8, FR-010, FR-013, FR-014).

Decisions store the binding tuple (version, content hash, run, rule set). Segregation of
duties is checked in the services first; the triggers here are a database backstop (BR-005).

Revision ID: 0008
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TUPLE = """
            dataset_version_id  uuid NOT NULL REFERENCES app.dataset_versions (id),
            content_hash        char(64) NOT NULL,
            validation_run_id   uuid NOT NULL REFERENCES app.validation_runs (id),
            rule_set_version_id uuid NOT NULL REFERENCES app.config_versions (id),
"""
UPDATABLE = {
    "app.issues": ("state", "state_changed_at"),
    "app.waivers": ("status", "stale_reason"),
    "app.review_requests": ("status", "stale_reason", "closed_at"),
}
INSERT_ONLY = ("app.issue_notes", "app.waiver_decisions", "app.approval_decisions")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.issues (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            finding_id         uuid NOT NULL UNIQUE REFERENCES app.findings (id),
            run_id             uuid NOT NULL REFERENCES app.validation_runs (id),
            dataset_version_id uuid NOT NULL REFERENCES app.dataset_versions (id),
            rule_id            text NOT NULL,
            severity           text NOT NULL CHECK (severity IN ('BLOCKING', 'WARNING')),
            waivable           boolean NOT NULL,
            state              text NOT NULL DEFAULT 'OPEN' CHECK (state IN
                               ('OPEN', 'WAIVER_REQUESTED', 'WAIVED', 'CLOSED_NOT_CURRENT')),
            state_changed_at   timestamptz NOT NULL DEFAULT now(),
            created_at         timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX issues_run_idx ON app.issues (run_id, severity, state)")
    op.execute(
        """
        CREATE TABLE app.issue_notes (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            issue_id   uuid NOT NULL REFERENCES app.issues (id),
            author_id  uuid NOT NULL REFERENCES app.users (id),
            body       text NOT NULL CHECK (length(body) BETWEEN 1 AND 5000),
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX issue_notes_issue_idx ON app.issue_notes (issue_id, created_at)")
    op.execute(
        f"""
        CREATE TABLE app.waivers (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            issue_id      uuid NOT NULL REFERENCES app.issues (id),
            {TUPLE}
            category      text NOT NULL CHECK (category IN
                          ('FALSE_POSITIVE', 'KNOWN_SOURCE_LIMITATION', 'IMMATERIAL', 'OTHER')),
            justification text NOT NULL CHECK (length(justification) >= 30),
            requested_by  uuid NOT NULL REFERENCES app.users (id),
            requested_at  timestamptz NOT NULL DEFAULT now(),
            status        text NOT NULL DEFAULT 'REQUESTED'
                          CHECK (status IN ('REQUESTED', 'GRANTED', 'DENIED', 'STALE')),
            stale_reason  text NULL CHECK (stale_reason IN
                          ('VERSION_SUPERSEDED', 'NEW_RUN', 'RULE_SET_CHANGED'))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX waivers_one_live_uq ON app.waivers (issue_id) "
        "WHERE status IN ('REQUESTED', 'GRANTED')"
    )
    op.execute(
        """
        CREATE TABLE app.waiver_decisions (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            waiver_id  uuid NOT NULL UNIQUE REFERENCES app.waivers (id),
            decision   text NOT NULL CHECK (decision IN ('GRANT', 'DENY')),
            decided_by uuid NOT NULL REFERENCES app.users (id),
            comment    text NULL,
            decided_at timestamptz NOT NULL DEFAULT now(),
            CHECK (decision = 'GRANT' OR length(comment) > 0)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE app.review_requests (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            {TUPLE}
            submitted_by uuid NOT NULL REFERENCES app.users (id),
            submitted_at timestamptz NOT NULL DEFAULT now(),
            note         text NOT NULL CHECK (length(note) > 0),
            snapshot     jsonb NOT NULL,
            status       text NOT NULL DEFAULT 'OPEN'
                         CHECK (status IN ('OPEN', 'APPROVED', 'REJECTED', 'STALE')),
            stale_reason text NULL CHECK (stale_reason IN
                         ('VERSION_SUPERSEDED', 'NEW_RUN', 'RULE_SET_CHANGED')),
            closed_at    timestamptz NULL
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX review_requests_one_open_uq ON app.review_requests "
        "(dataset_version_id) WHERE status = 'OPEN'"
    )
    op.execute(
        f"""
        CREATE TABLE app.approval_decisions (
            id                         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            review_request_id          uuid NOT NULL UNIQUE REFERENCES app.review_requests (id),
            {TUPLE}
            decision                   text NOT NULL CHECK (decision IN ('APPROVE', 'REJECT')),
            decided_by                 uuid NOT NULL REFERENCES app.users (id),
            comment                    text NULL,
            acknowledged_warning_count int NULL,
            decided_at                 timestamptz NOT NULL DEFAULT now(),
            CHECK (decision = 'APPROVE' OR length(comment) > 0)
        )
        """
    )

    tables = [*UPDATABLE, *INSERT_ONLY]
    op.execute(f"GRANT SELECT, INSERT ON {', '.join(tables)} TO sentinel_app")
    for table, columns in UPDATABLE.items():
        name = table.split(".")[1]
        op.execute(f"GRANT UPDATE ({', '.join(columns)}) ON {table} TO sentinel_app")
        args = ", ".join(f"'{c}'" for c in columns)
        op.execute(
            f"CREATE TRIGGER {name}_limit_update BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION app.sentinel_limit_update({args})"
        )
    for table in tables:
        name = table.split(".")[1]
        operations = (
            ("DELETE", "TRUNCATE") if table in UPDATABLE else ("UPDATE", "DELETE", "TRUNCATE")
        )
        for operation in operations:
            scope = "STATEMENT" if operation == "TRUNCATE" else "ROW"
            op.execute(
                f"CREATE TRIGGER {name}_forbid_{operation.lower()} BEFORE {operation} ON {table} "
                f"FOR EACH {scope} EXECUTE FUNCTION app.sentinel_forbid_change()"
            )

    # Segregation of duties by user ID (BR-005). TG_ARGV: parent table, parent key column on
    # NEW, parent's actor column.
    op.execute(
        """
        CREATE FUNCTION app.sentinel_segregation_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            other_party uuid;
        BEGIN
            EXECUTE format('SELECT %I FROM %s WHERE id = $1', TG_ARGV[2], TG_ARGV[0])
                INTO other_party USING (to_jsonb(NEW) ->> TG_ARGV[1])::uuid;
            IF other_party IS NULL OR other_party = NEW.decided_by THEN
                RAISE EXCEPTION 'sentinel: segregation of duties: a decision on % must be made '
                                'by a different user', TG_ARGV[0]
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION app.sentinel_segregation_guard() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER waiver_decisions_segregation BEFORE INSERT ON app.waiver_decisions "
        "FOR EACH ROW EXECUTE FUNCTION "
        "app.sentinel_segregation_guard('app.waivers', 'waiver_id', 'requested_by')"
    )
    op.execute(
        "CREATE TRIGGER approval_decisions_segregation BEFORE INSERT ON app.approval_decisions "
        "FOR EACH ROW EXECUTE FUNCTION "
        "app.sentinel_segregation_guard('app.review_requests', 'review_request_id', 'submitted_by')"
    )


def downgrade() -> None:
    raise NotImplementedError("Sentinel migrations are forward-only")
