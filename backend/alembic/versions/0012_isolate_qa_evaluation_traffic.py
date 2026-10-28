"""isolate QA evaluation traffic from live quality metrics

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("qa_session")}
    indexes = {index["name"] for index in inspector.get_indexes("qa_session")}
    with op.batch_alter_table("qa_session") as batch:
        if "is_evaluation" not in columns:
            batch.add_column(
                sa.Column("is_evaluation", sa.Boolean(), nullable=False, server_default=sa.false())
            )
        if "ix_qa_session_is_evaluation" not in indexes:
            batch.create_index("ix_qa_session_is_evaluation", ["is_evaluation"], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("qa_session")}
    indexes = {index["name"] for index in inspector.get_indexes("qa_session")}
    with op.batch_alter_table("qa_session") as batch:
        if "ix_qa_session_is_evaluation" in indexes:
            batch.drop_index("ix_qa_session_is_evaluation")
        if "is_evaluation" in columns:
            batch.drop_column("is_evaluation")
