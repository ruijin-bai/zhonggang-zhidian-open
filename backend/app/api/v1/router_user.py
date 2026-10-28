"""User management endpoints (R4 only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_roles
from app.core.exceptions import ok
from app.core.security import hash_password
from app.db.base import gen_id
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.auth import UserCreate
from app.schemas.user import UserMe, PermissionOut
from app.services.auth.auth_service import get_user_permissions
from app.services.permission.rbac import viz_permissions

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=None)
async def list_users(
    _: User = Depends(require_roles("R4")),
    db: AsyncSession = Depends(get_db),
):
    users = list((await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all())
    return ok(
        [
            {
                "user_id": u.user_id,
                "username": u.username,
                "role": u.role,
                "org_id": u.org_id,
                "post": u.post,
                "secret_clearance": u.secret_clearance,
                "is_active": u.is_active,
            }
            for u in users
        ]
    )


@router.post("", response_model=None)
async def create_user(
    body: UserCreate,
    _: User = Depends(require_roles("R4")),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    if existing:
        from app.core.exceptions import BadRequestError

        raise BadRequestError("用户名已存在")
    user = User(
        user_id=gen_id("user"),
        username=body.username,
        hashed_password=hash_password(body.password),
        role=body.role,
        org_id=body.org_id,
        post=body.post,
        secret_clearance=body.secret_clearance,
    )
    db.add(user)
    await db.flush()
    await db.commit()
    return ok({"user_id": user.user_id})


@router.get("/me", response_model=None)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    perms = await get_user_permissions(db, user)
    return ok(
        UserMe(
            user_id=user.user_id,
            username=user.username,
            role=user.role,
            org_id=user.org_id,
            post=user.post,
            secret_clearance=user.secret_clearance,
            permissions=[PermissionOut(**p) for p in viz_permissions(perms)],
        ).model_dump()
    )
