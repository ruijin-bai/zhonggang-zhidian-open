"""Keep legacy rules and add explicit compound-asset evidence.

Revision ID: 0020
Revises: 0019
"""
from alembic import context, op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    # 0001 creates current metadata for an empty database. Existing 0019
    # databases still need ALTERs; the fresh chain must not add columns twice.
    offline = context.is_offline_mode()
    inspector = None if offline else sa.inspect(op.get_bind())
    columns = {} if offline else {c["name"]: c for c in inspector.get_columns("decision_rule")}
    indexes = set() if offline else {i["name"] for i in inspector.get_indexes("decision_rule")}
    foreign_columns = set() if offline else {tuple(f["constrained_columns"]) for f in inspector.get_foreign_keys("decision_rule")}
    with op.batch_alter_table("decision_rule") as batch:
        if "source_kind" not in columns:
            batch.add_column(sa.Column("source_kind", sa.String(16), nullable=False, server_default="regulation"))
        for column in ("file_id", "clause_id"):
            if offline or not columns[column]["nullable"]:
                batch.alter_column(column, existing_type=sa.String(32), nullable=True)
        for column in ("asset_version_id", "retrieval_unit_id"):
            if column not in columns:
                batch.add_column(sa.Column(column, sa.String(32), nullable=True))
        if ("asset_version_id",) not in foreign_columns:
            batch.create_foreign_key("fk_rule_asset_version", "asset_version", ["asset_version_id"], ["version_id"])
        if ("retrieval_unit_id",) not in foreign_columns:
            batch.create_foreign_key("fk_rule_retrieval_unit", "retrieval_unit", ["retrieval_unit_id"], ["unit_id"])
        for column in ("asset_version_id", "retrieval_unit_id"):
            name = "ix_decision_rule_" + column
            if name not in indexes:
                batch.create_index(name, [column])


def downgrade():
    connection = op.get_bind()
    remaining = connection.execute(sa.text("SELECT COUNT(*) FROM decision_rule WHERE source_kind <> 'regulation' OR file_id IS NULL OR clause_id IS NULL")).scalar()
    if remaining:
        raise RuntimeError("存在复合资料规则，回退会丢失证据。请先备份并显式处理这些规则。")
    # Fresh metadata may have unnamed FKs; batch naming gives those constraints
    # deterministic names so downgrade remains possible without losing rows.
    foreign_keys = {tuple(f["constrained_columns"]): f["name"] for f in sa.inspect(connection).get_foreign_keys("decision_rule")}
    convention = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table("decision_rule", naming_convention=convention) as batch:
        batch.drop_index("ix_decision_rule_retrieval_unit_id")
        batch.drop_index("ix_decision_rule_asset_version_id")
        batch.drop_constraint(foreign_keys[("retrieval_unit_id",)] or "fk_decision_rule_retrieval_unit_id_retrieval_unit", type_="foreignkey")
        batch.drop_constraint(foreign_keys[("asset_version_id",)] or "fk_decision_rule_asset_version_id_asset_version", type_="foreignkey")
        batch.drop_column("retrieval_unit_id")
        batch.drop_column("asset_version_id")
        batch.drop_column("source_kind")
        batch.alter_column("file_id", existing_type=sa.String(32), nullable=False)
        batch.alter_column("clause_id", existing_type=sa.String(32), nullable=False)
