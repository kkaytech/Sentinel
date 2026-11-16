"""Baseline: schemas, revocations and guard trigger functions (Doc 4 §4.1, ARD §7.3).

Revision ID: 0001
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = ("app", "data", "published", "audit")


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA {schema}")
    op.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    op.execute(f"REVOKE ALL ON SCHEMA {', '.join(SCHEMAS)} FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA app, data, audit TO sentinel_app")
    op.execute("GRANT USAGE ON SCHEMA published TO sentinel_app, sentinel_reader")
    op.execute(
        """
        DO $$
        BEGIN
            EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO sentinel_app, sentinel_reader',
                           current_database());
        END
        $$
        """
    )

    # Forbid UPDATE/DELETE/TRUNCATE on history for every role except the owner.
    op.execute(
        """
        CREATE FUNCTION app.sentinel_forbid_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF current_user = 'sentinel_owner' THEN
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                IF TG_OP = 'TRUNCATE' THEN RETURN NULL; END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'sentinel: % on %.% is not permitted',
                TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
                USING ERRCODE = 'insufficient_privilege';
        END
        $$
        """
    )

    # Allow UPDATE only of the columns named in the trigger arguments.
    op.execute(
        """
        CREATE FUNCTION app.sentinel_limit_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            old_row jsonb := to_jsonb(OLD);
            new_row jsonb := to_jsonb(NEW);
            i int;
        BEGIN
            IF current_user = 'sentinel_owner' THEN
                RETURN NEW;
            END IF;
            FOR i IN 0 .. TG_NARGS - 1 LOOP
                old_row := old_row - TG_ARGV[i];
                new_row := new_row - TG_ARGV[i];
            END LOOP;
            IF old_row IS DISTINCT FROM new_row THEN
                RAISE EXCEPTION 'sentinel: update of protected columns on %.% is not permitted',
                    TG_TABLE_SCHEMA, TG_TABLE_NAME
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )

    # Seal-on-commit: child rows may only be inserted in the transaction that created the
    # parent. TG_ARGV[0] = parent table (schema-qualified), TG_ARGV[1] = child FK column.
    op.execute(
        """
        CREATE FUNCTION app.sentinel_seal_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            same_xact boolean;
        BEGIN
            EXECUTE format(
                'SELECT creating_xact = pg_current_xact_id() FROM %s WHERE id = $1',
                TG_ARGV[0]
            ) INTO same_xact USING (to_jsonb(NEW) ->> TG_ARGV[1])::uuid;
            IF same_xact IS NOT TRUE THEN
                RAISE EXCEPTION 'sentinel: % is sealed; rows can only be added in the '
                                'transaction that created it', TG_ARGV[0]
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    for fn in ("sentinel_forbid_change", "sentinel_limit_update", "sentinel_seal_guard"):
        op.execute(f"REVOKE ALL ON FUNCTION app.{fn}() FROM PUBLIC")


def downgrade() -> None:
    raise NotImplementedError("Sentinel migrations are forward-only")
