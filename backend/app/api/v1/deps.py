"""API dependencies: auth resolution, user context, role gating."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.models.permission import Permission
from app.db.models.user import User
from app.db.session import get_db
from app.services.auth.auth_service import get_user_permissions

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if creds is None or not creds.credentials:
        raise UnauthorizedError()
    try:
        payload = decode_access_token(creds.credentials)
        user_id = payload.get("sub")
    except Exception:  # noqa: BLE001
        raise UnauthorizedError()
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError()
    return user


async def get_user_context(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, list[Permission]]:
    """Return (user, permissions) — required by retrieval / graph services."""
    permissions = await get_user_permissions(db, user)
    return user, permissions


def require_roles(*roles: str) -> Callable:
    """Dependency factory enforcing one of the given roles (RBAC)."""

    async def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise ForbiddenError()
        return user

    return _checker
