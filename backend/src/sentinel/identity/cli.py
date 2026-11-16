"""Bootstrap CLI: create a user (for example the first administrator).

    python -m sentinel.identity.cli create-user --username admin --display-name "Admin" \
        --role ADMIN

The password is read from SENTINEL_NEW_USER_PASSWORD, or prompted for without echo.
It is never accepted as a command-line argument (it would leak into shell history).
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from sentinel.identity.users import create_user_as_system
from sentinel.shared.authz import Role
from sentinel.shared.db import make_engine, unit_of_work
from sentinel.shared.errors import SentinelError
from sentinel.shared.settings import Settings, SettingsError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentinel.identity.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user")
    create.add_argument("--username", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument("--role", action="append", choices=[r.value for r in Role], required=True)
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_env()
    except SettingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    password = os.environ.get("SENTINEL_NEW_USER_PASSWORD") or getpass.getpass("Password: ")
    engine = make_engine(settings.app_database_url)
    try:
        with unit_of_work(engine) as conn:
            user = create_user_as_system(
                conn,
                username=args.username,
                display_name=args.display_name,
                password=password,
                roles=frozenset(Role(r) for r in args.role),
            )
    except SentinelError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(f"created user {user.username} ({', '.join(sorted(user.roles))}) id={user.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
