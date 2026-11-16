"""Issues, waivers, review and approval (Doc 4 §3.6, §3.7)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from sentinel.api.deps import AuthContext, current_auth, get_engine, protected
from sentinel.api.views import review_summary_view
from sentinel.review import service as review
from sentinel.shared.authz import Permission
from sentinel.shared.db import unit_of_work

router = APIRouter(prefix="/api/v1")


class NoteRequest(BaseModel):
    body: str = Field(max_length=6000)


class WaiverRequest(BaseModel):
    category: str = Field(default="", max_length=40)
    justification: str = Field(default="", max_length=5000)


class WaiverDecision(BaseModel):
    decision: Literal["GRANT", "DENY"]
    comment: str | None = Field(default=None, max_length=5000)


class ReviewRequest(BaseModel):
    note: str = Field(default="", max_length=5000)


class ReviewDecision(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    comment: str | None = Field(default=None, max_length=5000)
    acknowledged_warning_count: int | None = Field(default=None, ge=0)


def _list(items: list[Any]) -> dict[str, Any]:
    return {"items": items, "total": len(items), "limit": len(items), "offset": 0}


@router.get("/runs/{run_id}/issues", **protected(Permission.READ))
def get_issues(
    run_id: UUID,
    severity: Literal["BLOCKING", "WARNING"] | None = None,
    state: Literal["OPEN", "WAIVER_REQUESTED", "WAIVED", "CLOSED_NOT_CURRENT"] | None = None,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return _list(
            review.list_issues(ctx.principal, conn, run_id, severity=severity, state=state)
        )


@router.get("/issues/{issue_id}", **protected(Permission.READ))
def get_issue(
    issue_id: UUID,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return review.get_issue(ctx.principal, conn, issue_id)


@router.post("/issues/{issue_id}/notes", status_code=201, **protected(Permission.ADD_NOTE))
def post_note(
    issue_id: UUID,
    body: NoteRequest,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return review.add_note(ctx.principal, conn, issue_id, body.body)


@router.post("/issues/{issue_id}/waivers", status_code=201, **protected(Permission.REQUEST_WAIVER))
def post_waiver(
    issue_id: UUID,
    body: WaiverRequest,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return review.request_waiver(
            ctx.principal, conn, issue_id, body.category, body.justification
        )


@router.post("/waivers/{waiver_id}/decision", **protected(Permission.DECIDE_WAIVER))
def post_waiver_decision(
    waiver_id: UUID,
    body: WaiverDecision,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return review.decide_waiver(ctx.principal, conn, waiver_id, body.decision, body.comment)


@router.post(
    "/versions/{version_id}/review-requests", status_code=201, **protected(Permission.SUBMIT_REVIEW)
)
def post_review_request(
    version_id: UUID,
    body: ReviewRequest,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return review.submit_review(ctx.principal, conn, version_id, body.note)


@router.get("/versions/{version_id}/review-requests", **protected(Permission.READ))
def get_review_requests(
    version_id: UUID,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return _list(review.list_review_requests(ctx.principal, conn, version_id))


@router.post("/review-requests/{request_id}/decision", **protected(Permission.DECIDE_REVIEW))
def post_review_decision(
    request_id: UUID,
    body: ReviewDecision,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return review.decide_review(
            ctx.principal, conn, request_id, body.decision, body.comment,
            body.acknowledged_warning_count,
        )  # fmt: skip


@router.get("/versions/{version_id}/review-summary", **protected(Permission.READ))
def get_review_summary(
    version_id: UUID,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        return review_summary_view(ctx.principal, conn, version_id)
