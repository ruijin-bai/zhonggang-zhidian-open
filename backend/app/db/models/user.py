"""User account with role and secret clearance."""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, gen_id
from app.db.enums import Role, SecretLevel


class User(Base, TimestampMixin):
    __tablename__ = "user"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("user"))
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("org_unit.org_id"), nullable=True)
    post: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(String(8), default=Role.R1.value)
    secret_clearance: Mapped[str] = mapped_column(String(16), default=SecretLevel.INTERNAL.value)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
