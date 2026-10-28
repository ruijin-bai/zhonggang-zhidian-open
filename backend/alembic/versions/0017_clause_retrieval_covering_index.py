"""cover SQLite permission-gated clause retrieval

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    names = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("clause")}
    if "ix_clause_retrieval_gate" not in names:
        op.create_index(
            "ix_clause_retrieval_gate",
            "clause",
            ["status", "secret_level", "file_id", "clause_id"],
        )


def downgrade() -> None:
    names = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("clause")}
    if "ix_clause_retrieval_gate" in names:
        op.drop_index("ix_clause_retrieval_gate", table_name="clause")
