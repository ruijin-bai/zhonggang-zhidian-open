"""feedback resolution workflow

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Early installations created tables from the then-current ORM metadata,
    # so these columns can already exist even when Alembic is only at 0008.
    # Keep the migration resumable for both those databases and clean installs.
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("qa_feedback")
    }
    additions = (
        ("resolved", sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("resolved_by", sa.Column("resolved_by", sa.String(32), nullable=True)),
        ("resolved_note", sa.Column("resolved_note", sa.Text(), nullable=True)),
        ("resolved_at", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True)),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column("qa_feedback", column)


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("qa_feedback")
    }
    for name in ("resolved_at", "resolved_note", "resolved_by", "resolved"):
        if name in columns:
            op.drop_column("qa_feedback", name)
