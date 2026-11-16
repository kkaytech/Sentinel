"""User administration endpoints (ADMIN only; Doc 4 §3.1)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import Engine

from sentinel.api.deps import AuthContext, current_auth, get_engine, protected
from sentinel.identity import users as user_service
from sentinel.shared.authz import Permission, Role
from sentinel.shared.db import unit_of_work

router = APIRouter(prefix="/api/v1")


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)
    roles: list[Role] = Field(min_length=1)


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    password: str | None = Field(default=None, min_length=1, max_length=1024)
    is_active: bool | None = None
    roles: list[Role] | None = None


@router.get("/users", **protected(Permission.MANAGE_USERS))
def get_users(
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        items = [u.as_dict() for u in user_service.list_users(ctx.principal, conn)]
    return {"items": items, "total": len(items), "limit": len(items), "offset": 0}


@router.post("/users", status_code=201, **protected(Permission.MANAGE_USERS))
def post_user(
    body: CreateUserRequest,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        user = user_service.create_user(
            ctx.principal,
            conn,
            username=body.username,
            display_name=body.display_name,
            password=body.password,
            roles=frozenset(body.roles),
        )
    return user.as_dict()


@router.patch("/users/{user_id}", **protected(Permission.MANAGE_USERS))
def patch_user(
    user_id: UUID,
    body: UpdateUserRequest,
    ctx: AuthContext = Depends(current_auth),  # noqa: B008
    engine: Engine = Depends(get_engine),  # noqa: B008
) -> dict[str, Any]:
    with unit_of_work(engine) as conn:
        user = user_service.update_user(
            ctx.principal,
            conn,
            user_id,
            display_name=body.display_name,
            password=body.password,
            is_active=body.is_active,
            roles=frozenset(body.roles) if body.roles is not None else None,
        )
    return user.as_dict()
