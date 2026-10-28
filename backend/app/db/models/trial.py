"""Privacy-minimised competition trial usage and benchmark records."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, gen_id


class TrialUsageEvent(Base):
    __tablename__ = "trial_usage_event"

    event_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("trialevt"))
    user_id: Mapped[str] = mapped_column(ForeignKey("user.user_id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(8), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scenario: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    result_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    need_human: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    authority_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    grounding_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    latency_first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_total_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_trial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TrialBenchmarkRecord(Base):
    __tablename__ = "trial_benchmark_record"

    record_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("trialbm"))
    scenario: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    participant_id_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    manual_duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    ai_duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    manual_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ai_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    manual_source_found: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ai_source_found: Mapped[bool] = mapped_column(Boolean, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
