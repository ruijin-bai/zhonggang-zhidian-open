"""Organization unit (总部 / 区域公司 / 驻外机构) with materialized path."""
from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, gen_id
from app.db.enums import OrgType


class OrgUnit(Base, TimestampMixin):
    __tablename__ = "org_unit"

    org_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("org"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("org_unit.org_id"), nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    org_type: Mapped[str] = mapped_column(String(16), default=OrgType.HEADQUARTER.value)
    # Materialized path, e.g. "/hq/region1/overseas1"; used by RBAC prefix filter.
    path: Mapped[str] = mapped_column(String(255), nullable=False, default="/")
