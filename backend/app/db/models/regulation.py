"""Regulation file (制度文件) with version and publication ledger."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, gen_id
from app.db.enums import RegulationStatus


class RegulationFile(Base, TimestampMixin):
    __tablename__ = "regulation_file"
    __table_args__ = (
        Index(
            "ix_regulation_file_vector_cache_state",
            "status",
            "updated_at",
            "file_id",
        ),
    )

    file_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("file"))
    # Stable business identifier shared by every version of the same regulation.
    regulation_code: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String(16), default=RegulationStatus.CURRENT.value)

    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # A new version may replace one currently published file.  The release
    # service performs the corresponding state transition atomically.
    replaces_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("regulation_file.file_id"), nullable=True, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("user.user_id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_confirmation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Safe, user-visible failure reason for parsing or publication readiness.
    ingest_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Transparent parser provenance and machine-readable quality evidence.
    parse_backend: Mapped[str] = mapped_column(String(32), nullable=False, default="legacy")
    parse_quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parse_quality_report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    owner_org: Mapped[str | None] = mapped_column(ForeignKey("org_unit.org_id"), nullable=True)
    # Denormalized owner path for efficient RBAC prefix filtering.
    org_path: Mapped[str] = mapped_column(String(255), nullable=False, default="/")
    secret_level: Mapped[str] = mapped_column(String(16), default="internal")
    # 制度域; "*" means all domains.
    domain: Mapped[str] = mapped_column(String(64), nullable=False, default="*")
    lang: Mapped[str] = mapped_column(String(8), default="zh")
    object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 文档级摘要（LLM 生成，用于两阶段召回与回答上下文聚合）。
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    clauses: Mapped[list["Clause"]] = relationship(  # noqa: F821
        "Clause", back_populates="file", cascade="all, delete-orphan"
    )
    documents: Mapped[list["RegulationDocument"]] = relationship(  # noqa: F821
        "RegulationDocument", back_populates="file", cascade="all, delete-orphan"
    )
    tags: Mapped[list["Tag"]] = relationship(  # noqa: F821
        "Tag", secondary="regulation_tag", back_populates="regulations"
    )
