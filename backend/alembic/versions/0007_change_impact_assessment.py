"""Add durable regulation change impact assessment.

Revision ID: 0007
Revises: 0006
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("change_impact_run"):
        op.create_table(
            "change_impact_run",
            sa.Column("impact_id", sa.String(length=32), primary_key=True),
            sa.Column("new_file_id", sa.String(length=32), sa.ForeignKey("regulation_file.file_id"), nullable=False),
            sa.Column("old_file_id", sa.String(length=32), sa.ForeignKey("regulation_file.file_id"), nullable=True),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
            sa.Column("summary", sa.JSON(), nullable=False),
            sa.Column("generated_by", sa.String(length=32), sa.ForeignKey("user.user_id"), nullable=True),
            sa.Column("confirmed_by", sa.String(length=32), sa.ForeignKey("user.user_id"), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("confirmation_note", sa.String(length=512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_change_impact_run_new_file_id", "change_impact_run", ["new_file_id"])
        op.create_index("ix_change_impact_run_old_file_id", "change_impact_run", ["old_file_id"])
        op.create_index("ix_change_impact_run_status", "change_impact_run", ["status"])
    if not inspector.has_table("change_impact_item"):
        op.create_table(
            "change_impact_item",
            sa.Column("item_id", sa.String(length=32), primary_key=True),
            sa.Column("impact_id", sa.String(length=32), sa.ForeignKey("change_impact_run.impact_id"), nullable=False),
            sa.Column("item_type", sa.String(length=48), nullable=False),
            sa.Column("object_type", sa.String(length=32), nullable=False),
            sa.Column("object_id", sa.String(length=64), nullable=True),
            sa.Column("severity", sa.String(length=16), nullable=False, server_default="medium"),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
            sa.Column("old_snapshot", sa.JSON(), nullable=False),
            sa.Column("new_snapshot", sa.JSON(), nullable=False),
            sa.Column("resolution", sa.Text(), nullable=True),
            sa.Column("resolved_by", sa.String(length=32), sa.ForeignKey("user.user_id"), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_change_impact_item_impact_id", "change_impact_item", ["impact_id"])
        op.create_index("ix_change_impact_item_item_type", "change_impact_item", ["item_type"])
        op.create_index("ix_change_impact_item_object_id", "change_impact_item", ["object_id"])
        op.create_index("ix_change_impact_item_status", "change_impact_item", ["status"])


def downgrade() -> None:
    pass
