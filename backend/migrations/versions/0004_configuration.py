"""Configuration versions and the active pointer (Doc 4 §4.4, FR-002).

Revision ID: 0004
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No unique constraint on the content hash: reverting to old content creates a new row,
    # so a binding tuple can never become valid again (Doc 4 §4.4).
    op.execute(
        """
        CREATE TABLE app.config_versions (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            kind           text NOT NULL CHECK (kind IN ('CONTRACT', 'RULE_SET')),
            dataset_key    text NOT NULL,
            content_sha256 char(64) NOT NULL,
            source_text    text NOT NULL,
            canonical_json text NOT NULL,
            loaded_by      uuid NULL REFERENCES app.users (id),
            loaded_at      timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX config_versions_lookup_idx ON app.config_versions "
        "(dataset_key, kind, loaded_at)"
    )
    op.execute(
        """
        CREATE TABLE app.active_config (
            dataset_key         text PRIMARY KEY,
            contract_version_id uuid NOT NULL REFERENCES app.config_versions (id),
            rule_set_version_id uuid NOT NULL REFERENCES app.config_versions (id),
            activated_at        timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("GRANT SELECT, INSERT ON app.config_versions, app.active_config TO sentinel_app")
    op.execute(
        "GRANT UPDATE (contract_version_id, rule_set_version_id, activated_at) "
        "ON app.active_config TO sentinel_app"
    )

    for when, scope in (("UPDATE", "ROW"), ("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")):
        op.execute(
            f"CREATE TRIGGER config_versions_forbid_{when.lower()} BEFORE {when} "
            f"ON app.config_versions FOR EACH {scope} "
            "EXECUTE FUNCTION app.sentinel_forbid_change()"
        )
    op.execute(
        "CREATE TRIGGER active_config_limit_update BEFORE UPDATE ON app.active_config "
        "FOR EACH ROW EXECUTE FUNCTION app.sentinel_limit_update("
        "'contract_version_id', 'rule_set_version_id', 'activated_at')"
    )
    for when, scope in (("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")):
        op.execute(
            f"CREATE TRIGGER active_config_forbid_{when.lower()} BEFORE {when} "
            f"ON app.active_config FOR EACH {scope} EXECUTE FUNCTION app.sentinel_forbid_change()"
        )


def downgrade() -> None:
    raise NotImplementedError("Sentinel migrations are forward-only")
