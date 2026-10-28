"""claim grounding, authority signals and source anchors

Revision ID: 0014
Revises: 0013
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    qa_columns = _columns("qa_session")
    with op.batch_alter_table("qa_session") as batch:
        if "grounding_passed" not in qa_columns:
            batch.add_column(sa.Column("grounding_passed", sa.Boolean(), nullable=False, server_default=sa.false()))
        if "grounding_coverage" not in qa_columns:
            batch.add_column(sa.Column("grounding_coverage", sa.Float(), nullable=False, server_default="0"))
        if "authority_verified" not in qa_columns:
            batch.add_column(sa.Column("authority_verified", sa.Boolean(), nullable=False, server_default=sa.false()))

    citation_columns = _columns("qa_citation")
    with op.batch_alter_table("qa_citation") as batch:
        if "source_page" not in citation_columns:
            batch.add_column(sa.Column("source_page", sa.Integer(), nullable=True))
        if "content_hash" not in citation_columns:
            batch.add_column(sa.Column("content_hash", sa.String(length=64), nullable=True))

    clause_columns = _columns("clause")
    with op.batch_alter_table("clause") as batch:
        if "source_page" not in clause_columns:
            batch.add_column(sa.Column("source_page", sa.Integer(), nullable=True))
        if "source_locator" not in clause_columns:
            batch.add_column(sa.Column("source_locator", sa.String(length=255), nullable=True))
        if "content_hash" not in clause_columns:
            batch.add_column(sa.Column("content_hash", sa.String(length=64), nullable=True))
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("clause")}
    if "ix_clause_content_hash" not in indexes:
        op.create_index("ix_clause_content_hash", "clause", ["content_hash"], unique=False)

    run_columns = _columns("test_run")
    with op.batch_alter_table("test_run") as batch:
        if "grounding_match" not in run_columns:
            batch.add_column(sa.Column("grounding_match", sa.Boolean(), nullable=False, server_default=sa.false()))
        if "answer_match" not in run_columns:
            batch.add_column(sa.Column("answer_match", sa.Boolean(), nullable=False, server_default=sa.false()))
        if "authority_match" not in run_columns:
            batch.add_column(sa.Column("authority_match", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("test_run") as batch:
        batch.drop_column("authority_match")
        batch.drop_column("answer_match")
        batch.drop_column("grounding_match")
    with op.batch_alter_table("qa_session") as batch:
        batch.drop_column("authority_verified")
        batch.drop_column("grounding_coverage")
        batch.drop_column("grounding_passed")
    with op.batch_alter_table("qa_citation") as batch:
        batch.drop_column("content_hash")
        batch.drop_column("source_page")
    op.drop_index("ix_clause_content_hash", table_name="clause")
    with op.batch_alter_table("clause") as batch:
        batch.drop_column("content_hash")
        batch.drop_column("source_locator")
        batch.drop_column("source_page")
