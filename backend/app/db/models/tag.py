"""Tag (标签) for business scenario / applicable object / regulation domain."""
from __future__ import annotations

from sqlalchemy import String, Table, ForeignKey, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, gen_id


# Association table linking clauses to tags (many-to-many).
clause_tag = Table(
    "clause_tag",
    Base.metadata,
    Column("clause_id", ForeignKey("clause.clause_id"), primary_key=True),
    Column("tag_id", ForeignKey("tag.tag_id"), primary_key=True),
)

# Association table linking regulations to classification tags (many-to-many).
regulation_tag = Table(
    "regulation_tag",
    Base.metadata,
    Column("file_id", ForeignKey("regulation_file.file_id"), primary_key=True),
    Column("tag_id", ForeignKey("tag.tag_id"), primary_key=True),
)


class Tag(Base):
    __tablename__ = "tag"

    tag_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("tag"))
    tag_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 业务场景/适用对象/制度分类
    tag_value: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    clauses: Mapped[list["Clause"]] = relationship(  # noqa: F821
        "Clause", secondary=clause_tag, back_populates="tags"
    )
    regulations: Mapped[list["RegulationFile"]] = relationship(  # noqa: F821
        "RegulationFile", secondary=regulation_tag, back_populates="tags"
    )
