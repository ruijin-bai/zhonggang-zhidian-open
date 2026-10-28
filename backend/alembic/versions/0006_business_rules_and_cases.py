"""Add governed decision rules and business-matter workflow.

Revision ID: 0006
Revises: 0005
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("decision_rule"):
        op.create_table(
            "decision_rule",
            sa.Column("rule_id", sa.String(length=32), primary_key=True),
            sa.Column("rule_key", sa.String(length=96), nullable=False),
            sa.Column("scenario", sa.String(length=64), nullable=False),
            sa.Column("rule_type", sa.String(length=32), nullable=False, server_default="approval"),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="pending_review"),
            sa.Column("file_id", sa.String(length=32), sa.ForeignKey("regulation_file.file_id"), nullable=False),
            sa.Column("clause_id", sa.String(length=32), sa.ForeignKey("clause.clause_id"), nullable=False),
            sa.Column("currency", sa.String(length=8), nullable=False, server_default="*"),
            sa.Column("amount_min_minor", sa.Integer(), nullable=True),
            sa.Column("amount_max_minor", sa.Integer(), nullable=True),
            sa.Column("min_inclusive", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("max_inclusive", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("org_scope", sa.String(length=255), nullable=False, server_default="/"),
            sa.Column("conditions", sa.JSON(), nullable=False),
            sa.Column("approver_path", sa.JSON(), nullable=False),
            sa.Column("required_materials", sa.JSON(), nullable=False),
            sa.Column("risk_note", sa.Text(), nullable=True),
            sa.Column("effective_from", sa.Date(), nullable=True),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("created_by", sa.String(length=32), sa.ForeignKey("user.user_id"), nullable=True),
            sa.Column("reviewed_by", sa.String(length=32), sa.ForeignKey("user.user_id"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("review_note", sa.String(length=512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_decision_rule_rule_key", "decision_rule", ["rule_key"])
        op.create_index("ix_decision_rule_scenario", "decision_rule", ["scenario"])
        op.create_index("ix_decision_rule_status", "decision_rule", ["status"])
        op.create_index("ix_decision_rule_file_id", "decision_rule", ["file_id"])
        op.create_index("ix_decision_rule_clause_id", "decision_rule", ["clause_id"])
    if not inspector.has_table("business_case"):
        op.create_table(
            "business_case",
            sa.Column("case_id", sa.String(length=32), primary_key=True),
            sa.Column("case_no", sa.String(length=48), nullable=False, unique=True),
            sa.Column("requester_id", sa.String(length=32), sa.ForeignKey("user.user_id"), nullable=False),
            sa.Column("scenario", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("org_path", sa.String(length=255), nullable=False, server_default="/"),
            sa.Column("project_code", sa.String(length=64), nullable=True),
            sa.Column("amount_minor", sa.Integer(), nullable=True),
            sa.Column("currency", sa.String(length=8), nullable=True),
            sa.Column("facts", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
            sa.Column("risk_level", sa.String(length=16), nullable=False, server_default="medium"),
            sa.Column("need_human", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("decision_summary", sa.Text(), nullable=True),
            sa.Column("decision_snapshot", sa.JSON(), nullable=False),
            sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reviewed_by", sa.String(length=32), sa.ForeignKey("user.user_id"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("review_note", sa.String(length=512), nullable=True),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_business_case_case_no", "business_case", ["case_no"])
        op.create_index("ix_business_case_requester_id", "business_case", ["requester_id"])
        op.create_index("ix_business_case_scenario", "business_case", ["scenario"])
        op.create_index("ix_business_case_status", "business_case", ["status"])


def downgrade() -> None:
    # Deliberately retained for audit evidence; destructive rollback is not automatic.
    pass
