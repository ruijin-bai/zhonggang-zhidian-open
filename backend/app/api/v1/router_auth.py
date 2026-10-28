"""Authentication & current-user endpoints."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.config import get_settings
from app.core.exceptions import ok, UnauthorizedError
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.auth import DemoIdentity, LoginRequest, TokenResponse, UserInfo
from app.schemas.user import PermissionOut, UserMe
from app.services.auth.auth_service import authenticate, get_user_permissions, issue_token
from app.services.permission.rbac import viz_permissions

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

DEMO_IDENTITIES = (
    ("employee", "R1", "员工", "驻外业务岗", "查询制度、发起问答与提交业务事项"),
    ("reviewer", "R2", "审核员", "合规骨干", "审核发布、处理纠错与确认影响项"),
    ("kbadmin", "R3", "知识管理员", "知识库管理员", "维护制度、条款、规则与关系图谱"),
    ("admin", "R4", "系统管理员", "系统管理员", "查看全部模块并管理系统配置"),
)


def _token_payload(user: User) -> dict:
    return TokenResponse(
        access_token=issue_token(user),
        user=UserInfo(
            user_id=user.user_id,
            username=user.username,
            role=user.role,
            org_id=user.org_id,
            post=user.post,
            secret_clearance=user.secret_clearance,
        ),
    ).model_dump()


async def _authenticate_development_identity(
    db: AsyncSession, username: str, password: str
) -> User | None:
    if not settings.DEMO_LOGIN_ENABLED or not settings.DEMO_LOGIN_PASSWORD:
        return None
    allowed = {identity[0] for identity in DEMO_IDENTITIES}
    if username not in allowed or not secrets.compare_digest(password, settings.DEMO_LOGIN_PASSWORD):
        return None
    return (
        await db.execute(
            select(User).where(User.username == username, User.is_active.is_(True))
        )
    ).scalar_one_or_none()


@router.get("/demo-identities", response_model=None)
async def demo_identities():
    if not settings.DEMO_LOGIN_ENABLED or not settings.DEMO_LOGIN_PASSWORD:
        return ok({"enabled": False, "identities": []})
    identities = [
        DemoIdentity(
            username=username,
            password=settings.DEMO_LOGIN_PASSWORD,
            role=role,
            role_label=role_label,
            post=post,
            description=description,
        ).model_dump()
        for username, role, role_label, post, description in DEMO_IDENTITIES
    ]
    return ok({"enabled": True, "identities": identities})


@router.post("/login", response_model=None)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await authenticate(db, body.username, body.password)
    if user is None:
        user = await _authenticate_development_identity(db, body.username, body.password)
    if user is None:
        raise UnauthorizedError("用户名或密码错误")
    return ok(_token_payload(user))


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
