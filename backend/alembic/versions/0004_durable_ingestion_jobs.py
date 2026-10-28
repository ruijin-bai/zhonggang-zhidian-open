"""Add durable regulation ingestion jobs.

Revision ID: 0004
Revises: 0003
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("ingestion_job"):
        return
    op.create_table(
        "ingestion_job",
        sa.Column("job_id", sa.String(length=32), primary_key=True),
        sa.Column("file_id", sa.String(length=32), sa.ForeignKey("regulation_file.file_id"), nullable=False, unique=True),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ingestion_job_status", "ingestion_job", ["status"])
    op.create_index("ix_ingestion_job_file_id", "ingestion_job", ["file_id"])


def downgrade() -> None:
    pass
