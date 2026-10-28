"""structured parser provenance and clause hierarchy

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    regulation_columns = _columns("regulation_file")
    with op.batch_alter_table("regulation_file") as batch:
        if "parse_backend" not in regulation_columns:
            batch.add_column(sa.Column("parse_backend", sa.String(32), nullable=False, server_default="legacy"))
        if "parse_quality_score" not in regulation_columns:
            batch.add_column(sa.Column("parse_quality_score", sa.Integer(), nullable=True))
        if "parse_quality_report" not in regulation_columns:
            batch.add_column(sa.Column("parse_quality_report", sa.JSON(), nullable=False, server_default="{}"))
    clause_columns = _columns("clause")
    with op.batch_alter_table("clause") as batch:
        if "heading_path" not in clause_columns:
            batch.add_column(sa.Column("heading_path", sa.JSON(), nullable=False, server_default="[]"))
        if "block_type" not in clause_columns:
            batch.add_column(sa.Column("block_type", sa.String(24), nullable=False, server_default="paragraph"))


def downgrade() -> None:
    with op.batch_alter_table("clause") as batch:
        batch.drop_column("block_type")
        batch.drop_column("heading_path")
    with op.batch_alter_table("regulation_file") as batch:
        batch.drop_column("parse_quality_report")
        batch.drop_column("parse_quality_score")
        batch.drop_column("parse_backend")
