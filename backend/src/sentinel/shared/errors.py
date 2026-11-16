"""Domain errors mapped to the API error envelope (Doc 4 §2.3, FS §8)."""

from __future__ import annotations

from typing import Any


class SentinelError(Exception):
    """An expected, user-facing failure with a stable error code.

    `message` must be safe to display: never include SQL, stack traces or data cell values.
    """

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def unauthenticated(code: str = "UNAUTHENTICATED") -> SentinelError:
    return SentinelError(401, code, "Authentication required.")


def permission_denied() -> SentinelError:
    return SentinelError(403, "PERMISSION_DENIED", "You do not have permission for this action.")


def not_found(what: str = "Resource") -> SentinelError:
    return SentinelError(404, "NOT_FOUND", f"{what} not found.")


def validation_error(message: str, details: dict[str, Any] | None = None) -> SentinelError:
    return SentinelError(422, "VALIDATION_ERROR", message, details)
