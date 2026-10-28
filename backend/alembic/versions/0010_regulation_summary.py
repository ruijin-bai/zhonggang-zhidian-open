"""regulation summary for two-stage retrieval

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite development databases may have received this column through
    # metadata.create_all before Alembic was run. Keep the migration resumable.
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("regulation_file")}
    if "summary" not in columns:
        op.add_column("regulation_file", sa.Column("summary", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("regulation_file")}
    if "summary" in columns:
        op.drop_column("regulation_file", "summary")
