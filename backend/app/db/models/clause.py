"""Clause (条款) — the minimal citable unit, carrying the embedding vector."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.db.base import Base, EmbeddingType, TimestampMixin, gen_id
from app.db.enums import ClauseStatus


class Clause(Base, TimestampMixin):
    __tablename__ = "clause"
    __table_args__ = (
        Index(
            "ix_clause_retrieval_gate",
            "status",
            "secret_level",
            "file_id",
            "clause_id",
        ),
        Index(
            "ix_clause_vector_cache_state",
            "status",
            "updated_at",
            "clause_id",
        ),
    )

    clause_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("clause"))
    file_id: Mapped[str] = mapped_column(ForeignKey("regulation_file.file_id"), nullable=False, index=True)
    chapter: Mapped[str | None] = mapped_column(String(64), nullable=True)
    clause_no: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Stable source anchors for audit and one-click return to the original.
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_locator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    heading_path: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    block_type: Mapped[str] = mapped_column(String(24), nullable=False, default="paragraph")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    permission_level: Mapped[str | None] = mapped_column(String(64), nullable=True)
    secret_level: Mapped[str] = mapped_column(String(16), default="internal")
    # Business scenario / applicable object tags (list of strings).
    scenario_tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    embedding: Mapped[list[float] | None] = mapped_column(
        EmbeddingType(get_settings().EMBED_DIM), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default=ClauseStatus.CURRENT.value)

    file: Mapped["RegulationFile"] = relationship("RegulationFile", back_populates="clauses")  # noqa: F821
    tags: Mapped[list["Tag"]] = relationship(  # noqa: F821
        "Tag", secondary="clause_tag", back_populates="clauses"
    )
