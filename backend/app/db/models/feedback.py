"""User feedback on QA answers (收藏 / 点赞 / 纠错)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, gen_id
from app.db.enums import FeedbackType


class QAFeedback(Base):
    __tablename__ = "qa_feedback"

    fb_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("fb"))
    session_id: Mapped[str] = mapped_column(ForeignKey("qa_session.session_id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("user.user_id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(16), default=FeedbackType.LIKE.value)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 纠错处理闭环（R2/R4 处理）
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    resolved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolved_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
