"""Auditable impact assessment generated when a regulation version is published."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, gen_id


class ChangeImpactRun(Base, TimestampMixin):
    __tablename__ = "change_impact_run"

    impact_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("impact"))
    new_file_id: Mapped[str] = mapped_column(ForeignKey("regulation_file.file_id"), nullable=False, index=True)
    old_file_id: Mapped[str | None] = mapped_column(ForeignKey("regulation_file.file_id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", index=True)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    generated_by: Mapped[str | None] = mapped_column(ForeignKey("user.user_id"), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("user.user_id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmation_note: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ChangeImpactItem(Base, TimestampMixin):
    __tablename__ = "change_impact_item"

    item_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("impactitem"))
    impact_id: Mapped[str] = mapped_column(ForeignKey("change_impact_run.impact_id"), nullable=False, index=True)
    item_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    old_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    new_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("user.user_id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
