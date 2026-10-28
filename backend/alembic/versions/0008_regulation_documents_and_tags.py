"""Add regulation documents and classification tags.

Revision ID: 0008
Revises: 0007
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("regulation_document"):
        op.create_table(
            "regulation_document",
            sa.Column("doc_id", sa.String(length=32), primary_key=True),
            sa.Column("file_id", sa.String(length=32), sa.ForeignKey("regulation_file.file_id"), nullable=False),
            sa.Column("doc_type", sa.String(length=24), nullable=False, server_default="attachment"),
            sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("filename", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("object_key", sa.String(length=512), nullable=True),
            sa.Column("mime", sa.String(length=128), nullable=False, server_default="application/octet-stream"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("source_path", sa.String(length=1024), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_regulation_document_file_id", "regulation_document", ["file_id"])
        op.create_index("ix_regulation_document_doc_type", "regulation_document", ["doc_type"])
    if not inspector.has_table("regulation_tag"):
        op.create_table(
            "regulation_tag",
            sa.Column("file_id", sa.String(length=32), sa.ForeignKey("regulation_file.file_id"), primary_key=True),
            sa.Column("tag_id", sa.String(length=32), sa.ForeignKey("tag.tag_id"), primary_key=True),
        )


def downgrade() -> None:
    pass
