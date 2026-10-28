"""Cross-file relation (替代 / 从属 / 多制度约束 / 冲突)."""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, gen_id
from app.db.enums import RelationType


class Relation(Base, TimestampMixin):
    __tablename__ = "relation"

    rel_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("rel"))
    from_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    to_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    rel_type: Mapped[str] = mapped_column(String(16), default=RelationType.SUBORDINATE.value)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
