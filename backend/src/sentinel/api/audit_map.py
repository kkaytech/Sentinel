"""Expected audit events per state-changing route (FR-015.1, NFR-007.4).

Every POST/PUT/PATCH/DELETE route must appear here. A test fails if one is missing, and the
audit-coverage tests assert that each call writes only events of an expected type.
"""

from __future__ import annotations

AUDITED_ROUTES: dict[str, frozenset[str]] = {
    "POST /api/v1/auth/login": frozenset({"LOGIN_SUCCEEDED", "LOGIN_FAILED"}),
    "POST /api/v1/auth/logout": frozenset({"LOGOUT"}),
    "POST /api/v1/users": frozenset({"USER_CREATED"}),
    "PATCH /api/v1/users/{user_id}": frozenset({"USER_UPDATED"}),
    "POST /api/v1/admin/config/reload": frozenset(
        {
            "CONFIG_ACTIVATED",
            "CONFIG_RELOAD_UNCHANGED",
            "CONFIG_REJECTED",
            "ISSUES_CLOSED_NOT_CURRENT",
            "WAIVER_STALE",
            "REVIEW_REQUEST_STALE",
        }
    ),
    # A new version also writes one VERSION_SUPERSEDED event per version it replaces.
    "POST /api/v1/datasets/{key}/periods/{period}/ingestions": frozenset(
        {
            "VERSION_CREATED",
            "VERSION_SUPERSEDED",
            "INGESTION_DUPLICATE",
            "INGESTION_FAILED",
            "INGESTION_REJECTED",
            "ISSUES_CLOSED_NOT_CURRENT",
            "WAIVER_STALE",
            "REVIEW_REQUEST_STALE",
        }
    ),
    # The run executes within the request until the job queue arrives (M1 step 5).
    "POST /api/v1/versions/{version_id}/runs": frozenset(
        {
            "VALIDATION_RUN_STARTED",
            "VALIDATION_RUN_COMPLETED",
            "VALIDATION_RUN_FAILED",
            "ISSUES_OPENED",
            "ISSUES_CLOSED_NOT_CURRENT",
            "WAIVER_STALE",
            "REVIEW_REQUEST_STALE",
        }
    ),
    "POST /api/v1/issues/{issue_id}/notes": frozenset({"ISSUE_NOTE_ADDED"}),
    "POST /api/v1/issues/{issue_id}/waivers": frozenset({"WAIVER_REQUESTED"}),
    "POST /api/v1/waivers/{waiver_id}/decision": frozenset({"WAIVER_GRANTED", "WAIVER_DENIED"}),
    "POST /api/v1/versions/{version_id}/review-requests": frozenset({"REVIEW_SUBMITTED"}),
    "POST /api/v1/review-requests/{request_id}/decision": frozenset(
        {"REVIEW_APPROVED", "REVIEW_REJECTED"}
    ),
}
