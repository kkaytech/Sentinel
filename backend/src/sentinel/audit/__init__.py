"""Append-only audit trail (FR-015). `record` writes inside the caller's transaction."""

from sentinel.audit.service import AuditFilters, list_events, record

__all__ = ["AuditFilters", "list_events", "record"]
