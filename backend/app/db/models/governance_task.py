"""Persistent governance work items for metadata and rule construction."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, gen_id


class GovernanceTask(Base, TimestampMixin):
    __tablename__ = "governance_task"
    __table_args__ = (UniqueConstraint("task_key", name="uq_governance_task_key"),)

    task_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("gov"))
    task_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    file_id: Mapped[str] = mapped_column(ForeignKey("regulation_file.file_id"), nullable=False, index=True)
    clause_id: Mapped[str | None] = mapped_column(ForeignKey("clause.clause_id"), nullable=True, index=True)
    scenario: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    missing_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("user.user_id"), nullable=True, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("user.user_id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
