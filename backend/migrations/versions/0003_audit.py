"""Audit: append-only event log (Doc 4 §4.3, FR-015).

Revision ID: 0003
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # dataset_version_id gets its foreign key in migration 0005, once versions exist.
    op.execute(
        """
        CREATE TABLE audit.events (
            id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            event_id           uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
            occurred_at        timestamptz NOT NULL DEFAULT now(),
            actor_kind         text NOT NULL CHECK (actor_kind IN ('USER', 'SYSTEM')),
            actor_user_id      uuid NULL REFERENCES app.users (id),
            event_type         text NOT NULL CHECK (event_type ~ '^[A-Z][A-Z0-9_]*$'),
            entity_type        text NOT NULL,
            entity_id          text NOT NULL,
            dataset_version_id uuid NULL,
            payload            jsonb NOT NULL DEFAULT '{}'::jsonb,
            correlation_id     text NULL,
            CHECK ((actor_kind = 'USER') = (actor_user_id IS NOT NULL))
        )
        """
    )
    op.execute("CREATE INDEX events_version_idx ON audit.events (dataset_version_id, id)")
    op.execute("CREATE INDEX events_entity_idx ON audit.events (entity_type, entity_id, id)")
    op.execute("CREATE INDEX events_type_idx ON audit.events (event_type, id)")
    op.execute("CREATE INDEX events_time_idx ON audit.events (occurred_at)")

    op.execute("GRANT SELECT, INSERT ON audit.events TO sentinel_app")
    op.execute("GRANT USAGE ON SEQUENCE audit.events_id_seq TO sentinel_app")

    for when, scope in (("UPDATE", "ROW"), ("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")):
        op.execute(
            f"CREATE TRIGGER events_forbid_{when.lower()} BEFORE {when} ON audit.events "
            f"FOR EACH {scope} EXECUTE FUNCTION app.sentinel_forbid_change()"
        )


def downgrade() -> None:
    raise NotImplementedError("Sentinel migrations are forward-only")
