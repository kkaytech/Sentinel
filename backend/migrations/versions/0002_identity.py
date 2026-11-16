"""Identity: users, roles, sessions, login attempts (Doc 4 §4.2, ARD §7.3.2).

Revision ID: 0002
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _protect(table: str, *, updatable: tuple[str, ...], allow_delete: bool) -> None:
    name = table.replace(".", "_")
    if updatable:
        args = ", ".join(f"'{col}'" for col in updatable)
        op.execute(
            f"CREATE TRIGGER {name}_limit_update BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION app.sentinel_limit_update({args})"
        )
    else:
        op.execute(
            f"CREATE TRIGGER {name}_forbid_update BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION app.sentinel_forbid_change()"
        )
    if not allow_delete:
        op.execute(
            f"CREATE TRIGGER {name}_forbid_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION app.sentinel_forbid_change()"
        )
    op.execute(
        f"CREATE TRIGGER {name}_forbid_truncate BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION app.sentinel_forbid_change()"
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.users (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            username      text NOT NULL CHECK (username ~ '^[A-Za-z0-9_.-]{3,64}$'),
            display_name  text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
            password_hash text NOT NULL,
            is_active     boolean NOT NULL DEFAULT true,
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX users_username_lower_uq ON app.users (lower(username))")

    op.execute(
        """
        CREATE TABLE app.user_roles (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    uuid NOT NULL REFERENCES app.users (id),
            role       text NOT NULL CHECK (role IN ('ANALYST', 'APPROVER', 'ADMIN')),
            granted_by uuid NULL REFERENCES app.users (id),
            granted_at timestamptz NOT NULL DEFAULT now(),
            revoked_at timestamptz NULL,
            revoked_by uuid NULL REFERENCES app.users (id),
            CHECK (revoked_by IS NULL OR revoked_at IS NOT NULL)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX user_roles_active_uq ON app.user_roles (user_id, role) "
        "WHERE revoked_at IS NULL"
    )

    op.execute(
        """
        CREATE TABLE app.sessions (
            token_hmac   bytea PRIMARY KEY,
            user_id      uuid NOT NULL REFERENCES app.users (id),
            csrf_token   text NOT NULL,
            created_at   timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX sessions_user_idx ON app.sessions (user_id)")

    op.execute(
        """
        CREATE TABLE app.login_attempts (
            id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            username_lower text NOT NULL,
            attempted_at   timestamptz NOT NULL DEFAULT now(),
            succeeded      boolean NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX login_attempts_lookup_idx ON app.login_attempts "
        "(username_lower, attempted_at)"
    )

    op.execute("GRANT SELECT, INSERT ON app.users TO sentinel_app")
    op.execute(
        "GRANT UPDATE (display_name, password_hash, is_active, updated_at) "
        "ON app.users TO sentinel_app"
    )
    op.execute("GRANT SELECT, INSERT ON app.user_roles TO sentinel_app")
    op.execute("GRANT UPDATE (revoked_at, revoked_by) ON app.user_roles TO sentinel_app")
    op.execute("GRANT SELECT, INSERT, DELETE ON app.sessions TO sentinel_app")
    op.execute("GRANT UPDATE (last_seen_at) ON app.sessions TO sentinel_app")
    op.execute("GRANT SELECT, INSERT, DELETE ON app.login_attempts TO sentinel_app")
    op.execute("GRANT USAGE ON SEQUENCE app.login_attempts_id_seq TO sentinel_app")

    _protect(
        "app.users",
        updatable=("display_name", "password_hash", "is_active", "updated_at"),
        allow_delete=False,
    )
    _protect("app.user_roles", updatable=("revoked_at", "revoked_by"), allow_delete=False)
    _protect("app.sessions", updatable=("last_seen_at",), allow_delete=True)
    _protect("app.login_attempts", updatable=(), allow_delete=True)


def downgrade() -> None:
    raise NotImplementedError("Sentinel migrations are forward-only")
