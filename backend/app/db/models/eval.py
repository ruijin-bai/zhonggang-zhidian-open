"""Evaluation test cases and run results (评估闭环)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, gen_id
from app.db.enums import TestRunStatus, TestStatus


class TestCase(Base, TimestampMixin):
    __tablename__ = "test_case"

    case_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("case"))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_clause_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    standard_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scenario_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=TestStatus.ACTIVE.value)


class TestRun(Base):
    __tablename__ = "test_run"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("run"))
    case_id: Mapped[str] = mapped_column(ForeignKey("test_case.case_id"), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("qa_session.session_id"), nullable=False, index=True)
    recall_match: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    citation_match: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    grounding_match: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    answer_match: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    authority_match: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reviewer: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=TestRunStatus.PENDING.value)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
