"""Declarative base, timestamp mixin and a dialect-aware embedding column type.

``EmbeddingType`` stores the clause vector as a native ``pgvector`` column on
PostgreSQL (production path with ``VECTOR_BACKEND=pgvector``) and transparently
serialises it to JSON text on other backends (SQLite local fallback). This keeps
the same ORM model working in both environments.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, TypeDecorator, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def gen_id(prefix: str) -> str:
    """Generate a prefixed primary key, e.g. ``clause_9f3a...``."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class EmbeddingType(TypeDecorator):
    """Vector column that uses pgvector on PostgreSQL and JSON text elsewhere."""

    impl = String
    cache_ok = True

    def __init__(self, dim: int = 128) -> None:
        self.dim = dim
        super().__init__()

    def load_dialect_impl(self, dialect):  # type: ignore[override]
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return Vector(self.dim)
        # Non-postgres: store as JSON text.
        from sqlalchemy import Text

        return Text()

    def process_bind_param(self, value, dialect):  # type: ignore[override]
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):  # type: ignore[override]
        if value is None:
            return None
        if dialect.name == "postgresql":
            # pgvector returns a list of floats already.
            return [float(x) for x in value]
        return json.loads(value)
