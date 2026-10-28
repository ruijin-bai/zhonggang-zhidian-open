"""Authentication service: credential verification and permission resolution."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, verify_password
from app.db.models.permission import Permission
from app.db.models.user import User


async def authenticate(session: AsyncSession, username: str, password: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def get_user_permissions(session: AsyncSession, user: User) -> list[Permission]:
    result = await session.execute(select(Permission).where(Permission.role == user.role))
    return list(result.scalars().all())


def issue_token(user: User) -> str:
    return create_access_token(
        subject=user.user_id,
        extra={"role": user.role, "org_id": user.org_id, "username": user.username},
    )
