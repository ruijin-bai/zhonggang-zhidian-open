"""QA session and citation (溯源) records."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, gen_id


class QASession(Base):
    __tablename__ = "qa_session"

    session_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("qa"))
    user_id: Mapped[str] = mapped_column(ForeignKey("user.user_id"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_interpret: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Whether the answer was produced by the degraded (top-k concatenation) path.
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_evaluation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    need_human: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Claim-level quality signals, kept separately from retrieval confidence.
    grounding_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    grounding_coverage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    authority_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class QACitation(Base):
    __tablename__ = "qa_citation"

    cite_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("cite"))
    session_id: Mapped[str] = mapped_column(ForeignKey("qa_session.session_id"), nullable=False, index=True)
    clause_id: Mapped[str] = mapped_column(String(32), nullable=False)
    file_title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    clause_no: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    # Whether the excerpt is consistent with the source clause content.
    consistent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
