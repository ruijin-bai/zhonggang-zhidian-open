"""Auth & user DTOs."""
from __future__ import annotations

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class DemoIdentity(BaseModel):
    username: str
    password: str
    role: str
    role_label: str
    post: str
    description: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserInfo"


class UserInfo(BaseModel):
    user_id: str
    username: str
    role: str
    org_id: str | None = None
    post: str | None = None
    secret_clearance: str = "internal"


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "R1"
    org_id: str | None = None
    post: str | None = None
    secret_clearance: str = "internal"
