"""Runtime settings read from the environment (NFR-003)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ENVIRONMENTS = frozenset({"development", "demo", "test", "production"})
MIN_SESSION_SECRET_LENGTH = 32
# A source checkout keeps the configuration files at <repo>/config.
DEFAULT_CONFIG_DIR = str(Path(__file__).resolve().parents[4] / "config")


class SettingsError(RuntimeError):
    """Raised when required configuration is missing or invalid. The app must not start."""


@dataclass(frozen=True)
class Settings:
    app_database_url: str
    session_secret: str
    env: str
    https: bool = False
    session_idle_seconds: int = 8 * 3600  # NFR-002
    login_failure_limit: int = 10  # NFR-002
    login_window_seconds: int = 15 * 60  # NFR-002
    config_dir: str = DEFAULT_CONFIG_DIR  # FR-002
    frontend_dir: str | None = None  # the built UI; None when Vite serves it
    max_file_bytes: int = 20 * 1024 * 1024  # NFR-001
    max_rows: int = 200_000  # NFR-001
    finding_key_cap: int = 10_000  # NFR-001, FR-009

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        required = ("SENTINEL_APP_DATABASE_URL", "SENTINEL_SESSION_SECRET", "SENTINEL_ENV")
        missing = [name for name in required if not env.get(name)]
        if missing:
            raise SettingsError("Missing required environment variables: " + ", ".join(missing))
        settings = cls(
            app_database_url=env["SENTINEL_APP_DATABASE_URL"],
            session_secret=env["SENTINEL_SESSION_SECRET"],
            env=env["SENTINEL_ENV"],
            https=env.get("SENTINEL_HTTPS", "false").lower() == "true",
            config_dir=env.get("SENTINEL_CONFIG_DIR", DEFAULT_CONFIG_DIR),
            frontend_dir=env.get("SENTINEL_FRONTEND_DIR") or _default_frontend_dir(),
            max_file_bytes=_positive_int(env, "SENTINEL_MAX_FILE_MB", 20) * 1024 * 1024,
            max_rows=_positive_int(env, "SENTINEL_MAX_ROWS", 200_000),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.env not in ENVIRONMENTS:
            raise SettingsError(
                f"SENTINEL_ENV must be one of {sorted(ENVIRONMENTS)}, got {self.env!r}"
            )
        if len(self.session_secret) < MIN_SESSION_SECRET_LENGTH:
            raise SettingsError(
                f"SENTINEL_SESSION_SECRET must be at least {MIN_SESSION_SECRET_LENGTH} characters"
            )


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    if not raw.isdigit() or int(raw) <= 0:
        raise SettingsError(f"{name} must be a positive integer")
    return int(raw)


def _default_frontend_dir() -> str | None:
    """A source checkout serves frontend/dist when it has been built."""
    dist = Path(__file__).resolve().parents[4] / "frontend" / "dist"
    return str(dist) if (dist / "index.html").is_file() else None
