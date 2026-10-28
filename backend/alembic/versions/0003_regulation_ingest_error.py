"""Store visible regulation ingestion errors.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("regulation_file")}
    if "ingest_error" not in columns:
        op.add_column("regulation_file", sa.Column("ingest_error", sa.String(length=512), nullable=True))


def downgrade() -> None:
    pass
