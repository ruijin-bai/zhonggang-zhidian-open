"""Push records, read receipts and subscriptions for the update-push feature."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, gen_id
from app.db.enums import PushStatus, ReadStatus


class PushRecord(Base, TimestampMixin):
    __tablename__ = "push_record"

    push_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("push"))
    file_id: Mapped[str | None] = mapped_column(ForeignKey("regulation_file.file_id"), nullable=True)
    target_role: Mapped[str | None] = mapped_column(String(8), nullable=True)
    scenario_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    push_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(16), default=PushStatus.DRAFT.value)
    digest: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


class PushReceipt(Base):
    __tablename__ = "push_receipt"

    receipt_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("rcpt"))
    push_id: Mapped[str] = mapped_column(ForeignKey("push_record.push_id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("user.user_id"), nullable=False, index=True)
    read_status: Mapped[str] = mapped_column(String(8), default=ReadStatus.UNREAD.value)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PushSubscription(Base):
    __tablename__ = "push_subscription"

    sub_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("sub"))
    user_id: Mapped[str] = mapped_column(ForeignKey("user.user_id"), nullable=False, index=True)
    scenario_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
