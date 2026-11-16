"""Request-scoped context (correlation IDs for logs and audit events)."""

from __future__ import annotations

from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("sentinel_correlation_id", default=None)


def set_correlation_id(value: str | None) -> None:
    _correlation_id.set(value)


def current_correlation_id() -> str | None:
    return _correlation_id.get()
