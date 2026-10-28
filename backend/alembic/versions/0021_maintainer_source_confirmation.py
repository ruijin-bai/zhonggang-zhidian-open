"""Record maintainer source confirmation without inventing formal metadata.

Revision ID: 0021
Revises: 0020
"""
from alembic import context, op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    offline = context.is_offline_mode()
    columns = set() if offline else {row["name"] for row in sa.inspect(op.get_bind()).get_columns("regulation_file")}
    if "source_confirmation" not in columns:
        op.add_column("regulation_file", sa.Column("source_confirmation", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    # Downgrade is permitted only before confirmations exist, so it cannot
    # silently discard the user's chosen provenance and usable-source state.
    connection = op.get_bind()
    values = connection.execute(sa.text("SELECT source_confirmation FROM regulation_file")).scalars()
    if any(value not in (None, "{}", {}, "null") for value in values):
        raise RuntimeError("已有维护者来源确认，回退会丢失确认记录；请先备份并明确处理。")
    with op.batch_alter_table("regulation_file") as batch:
        batch.drop_column("source_confirmation")
