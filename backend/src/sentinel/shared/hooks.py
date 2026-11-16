"""In-process event hooks, so a lower module can announce an event that a higher one handles.

Staleness propagation (FS §2.6) must run in the same transaction as the event that causes it,
but `ingestion`, `validation` and `config` may not import `review` (ARD §6.2). They emit here;
the composition root registers the handlers. Handlers run synchronously on the caller's
connection, so they commit or roll back with the event.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection

Handler = Callable[..., None]
_handlers: dict[str, list[Handler]] = {}

VERSIONS_SUPERSEDED = "versions_superseded"  # version_ids: list[UUID]
RUN_STARTED = "run_started"  # version_id: UUID, run_id: UUID
RULE_SET_ACTIVATED = "rule_set_activated"  # dataset_key: str, rule_set_version_id: UUID


def register(event: str, handler: Handler) -> None:
    handlers = _handlers.setdefault(event, [])
    if handler not in handlers:
        handlers.append(handler)


def emit(event: str, conn: Connection, **payload: Any) -> None:
    for handler in _handlers.get(event, []):
        handler(conn, **payload)
