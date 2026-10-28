"""Regulation documents: the physical files that make up one regulation.

A single regulation is a logical unit that may be backed by several files:
the main body, attachments, historical versions, review opinions, the
issuance notice and training material.  This model keeps those files grouped
under ``RegulationFile`` without forcing every file into clause-level parsing.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, gen_id


class RegulationDocument(Base, TimestampMixin):
    __tablename__ = "regulation_document"

    doc_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("doc"))
    file_id: Mapped[str] = mapped_column(ForeignKey("regulation_file.file_id"), nullable=False, index=True)
    # main / attachment / history / review_opinion / notice / training
    doc_type: Mapped[str] = mapped_column(String(24), nullable=False, default="attachment", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    filename: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mime: Mapped[str] = mapped_column(String(128), nullable=False, default="application/octet-stream")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Original filesystem path at import time, kept for traceability.
    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    file: Mapped["RegulationFile"] = relationship(  # noqa: F821
        "RegulationFile", back_populates="documents"
    )
