"""Governed, deterministic business rules sourced from published clauses."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, gen_id
from app.db.enums import DecisionRuleStatus


class DecisionRule(Base, TimestampMixin):
    __tablename__ = "decision_rule"

    rule_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("rule"))
    # A stable key lets the impact service compare rule meaning across versions.
    rule_key: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    scenario: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False, default="approval")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DecisionRuleStatus.PENDING_REVIEW.value, index=True)

    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="regulation", server_default="regulation")
    file_id: Mapped[str | None] = mapped_column(ForeignKey("regulation_file.file_id"), nullable=True, index=True)
    clause_id: Mapped[str | None] = mapped_column(ForeignKey("clause.clause_id"), nullable=True, index=True)
    asset_version_id: Mapped[str | None] = mapped_column(ForeignKey("asset_version.version_id"), nullable=True, index=True)
    retrieval_unit_id: Mapped[str | None] = mapped_column(ForeignKey("retrieval_unit.unit_id"), nullable=True, index=True)
    # Monetary values use the smallest currency unit (for example cents) so
    # boundary decisions never depend on binary floating-point arithmetic.
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="*")
    amount_min_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_max_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_inclusive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_inclusive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    org_scope: Mapped[str] = mapped_column(String(255), nullable=False, default="/")
    conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    approver_path: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    required_materials: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    risk_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_by: Mapped[str | None] = mapped_column(ForeignKey("user.user_id"), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("user.user_id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
