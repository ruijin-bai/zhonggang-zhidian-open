"""Durable regulation-ingestion job ledger."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, gen_id


class IngestionJob(Base, TimestampMixin):
    """One recoverable ingestion job per uploaded regulation version."""

    __tablename__ = "ingestion_job"

    job_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("ingest"))
    file_id: Mapped[str] = mapped_column(ForeignKey("regulation_file.file_id"), nullable=False, unique=True, index=True)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
