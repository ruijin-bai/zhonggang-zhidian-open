"""Initial schema for 中港智典 (T02).

Creates every ORM table and enables the ``vector`` extension on PostgreSQL.
The schema is sourced from ``Base.metadata`` so it always matches the models.
"""
from __future__ import annotations

from alembic import op

from app.db.base import Base
from app.db import models  # noqa: F401  ensure all tables are registered


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
