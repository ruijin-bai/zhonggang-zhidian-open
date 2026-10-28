"""Permission row — the unit of RBAC policy (role × org scope × secret × domain)."""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, gen_id


class Permission(Base, TimestampMixin):
    __tablename__ = "permission"

    perm_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("perm"))
    role: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    # Org path prefix; resources whose org_path starts with this are visible.
    org_scope: Mapped[str] = mapped_column(String(255), nullable=False, default="/")
    # Max secret level the role may see.
    secret_level: Mapped[str] = mapped_column(String(16), nullable=False, default="internal")
    # 制度域 whitelist; "*" grants all domains.
    domain: Mapped[str] = mapped_column(String(64), nullable=False, default="*")
