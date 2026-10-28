"""Add accountable review fields to regulation release workflow.

Revision ID: 0005
Revises: 0004
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("regulation_file")}
    if "reviewed_by" not in columns:
        op.add_column("regulation_file", sa.Column("reviewed_by", sa.String(length=32), nullable=True))
    if "reviewed_at" not in columns:
        op.add_column("regulation_file", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    if "review_note" not in columns:
        op.add_column("regulation_file", sa.Column("review_note", sa.String(length=512), nullable=True))


def downgrade() -> None:
    pass
