"""Add regulation publication ledger fields.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    columns = _column_names("regulation_file")
    if "regulation_code" not in columns:
        op.add_column("regulation_file", sa.Column("regulation_code", sa.String(length=64), nullable=True))
        # Legacy records remain independently addressable without guessing a
        # business code from their titles.
        op.execute("UPDATE regulation_file SET regulation_code = file_id WHERE regulation_code IS NULL")
    if "replaces_file_id" not in columns:
        op.add_column("regulation_file", sa.Column("replaces_file_id", sa.String(length=32), nullable=True))
    if "published_at" not in columns:
        op.add_column("regulation_file", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))

    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("regulation_file")}
    if "ix_regulation_file_regulation_code" not in indexes:
        op.create_index("ix_regulation_file_regulation_code", "regulation_file", ["regulation_code"])


def downgrade() -> None:
    # Retain historical release data on downgrade; schema rollback must not
    # destroy the version ledger in a production database.
    pass
