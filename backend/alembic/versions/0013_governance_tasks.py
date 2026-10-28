"""persistent metadata and rule governance tasks

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("governance_task"):
        return
    op.create_table(
        "governance_task",
        sa.Column("task_id", sa.String(length=32), primary_key=True),
        sa.Column("task_key", sa.String(length=160), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("file_id", sa.String(length=32), sa.ForeignKey("regulation_file.file_id"), nullable=False),
        sa.Column("clause_id", sa.String(length=32), sa.ForeignKey("clause.clause_id"), nullable=True),
        sa.Column("scenario", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("missing_fields", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("assignee_id", sa.String(length=32), sa.ForeignKey("user.user_id"), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(length=32), sa.ForeignKey("user.user_id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_key", name="uq_governance_task_key"),
    )
    for column in ("task_key", "task_type", "file_id", "clause_id", "scenario", "status", "assignee_id"):
        op.create_index(f"ix_governance_task_{column}", "governance_task", [column], unique=False)


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("governance_task"):
        op.drop_table("governance_task")
