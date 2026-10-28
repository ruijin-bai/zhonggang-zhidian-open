"""User / permission context DTOs."""
from __future__ import annotations

from pydantic import BaseModel


class PermissionOut(BaseModel):
    role: str
    org_scope: str
    secret_level: str
    domain: str


class UserMe(BaseModel):
    user_id: str
    username: str
    role: str
    org_id: str | None = None
    post: str | None = None
    secret_clearance: str
    permissions: list[PermissionOut] = []
