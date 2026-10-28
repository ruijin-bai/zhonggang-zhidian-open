"""A traceable business matter evaluated against a governed rule snapshot."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, gen_id
from app.db.enums import BusinessCaseStatus


class BusinessCase(Base, TimestampMixin):
    __tablename__ = "business_case"

    case_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("case"))
    case_no: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    requester_id: Mapped[str] = mapped_column(ForeignKey("user.user_id"), nullable=False, index=True)
    scenario: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    org_path: Mapped[str] = mapped_column(String(255), nullable=False, default="/")
    project_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    facts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String(24), nullable=False, default=BusinessCaseStatus.DRAFT.value, index=True)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    need_human: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    decision_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("user.user_id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
