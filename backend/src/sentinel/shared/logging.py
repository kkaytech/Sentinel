"""Structured JSON logging (NFR-003). Never log data cell values, passwords, tokens or keys."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sentinel.shared.context import current_correlation_id

_RESERVED = set(vars(logging.makeLogRecord({})))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": current_correlation_id(),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(entry, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("sentinel")
    root.handlers = [handler]
    root.setLevel(level)
    root.propagate = False
