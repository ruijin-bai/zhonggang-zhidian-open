"""normalize legacy business scenario labels

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

SCENARIO_MAP = {
    "合同变更": "contract_change",
    "付款申请": "payment",
    "采购事项": "procurement",
    "安全事项": "safety",
    "安全生产费用": "safety",
    "用工事项": "employment",
}


def upgrade() -> None:
    for legacy, canonical in SCENARIO_MAP.items():
        op.execute(
            "UPDATE decision_rule SET scenario = '%s' WHERE scenario = '%s'" % (canonical, legacy)
        )
        op.execute(
            "UPDATE business_case SET scenario = '%s' WHERE scenario = '%s'" % (canonical, legacy)
        )


def downgrade() -> None:
    # Canonical values remain valid in earlier schemas. Reversing would lose
    # which legacy synonym was originally used, so keep them canonical.
    pass
