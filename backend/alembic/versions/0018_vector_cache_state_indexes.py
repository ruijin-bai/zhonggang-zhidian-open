"""index source-only vector cache signatures

Revision ID: 0018
Revises: 0017
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    clause_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("clause")}
    if "ix_clause_vector_cache_state" not in clause_indexes:
        op.create_index(
            "ix_clause_vector_cache_state",
            "clause",
            ["status", "updated_at", "clause_id"],
        )
    regulation_indexes = {
        item["name"] for item in sa.inspect(bind).get_indexes("regulation_file")
    }
    if "ix_regulation_file_vector_cache_state" not in regulation_indexes:
        op.create_index(
            "ix_regulation_file_vector_cache_state",
            "regulation_file",
            ["status", "updated_at", "file_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    regulation_indexes = {
        item["name"] for item in sa.inspect(bind).get_indexes("regulation_file")
    }
    if "ix_regulation_file_vector_cache_state" in regulation_indexes:
        op.drop_index("ix_regulation_file_vector_cache_state", table_name="regulation_file")
    clause_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("clause")}
    if "ix_clause_vector_cache_state" in clause_indexes:
        op.drop_index("ix_clause_vector_cache_state", table_name="clause")
