"""real trial usage and benchmark evidence

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("trial_usage_event"):
        op.create_table(
            "trial_usage_event",
            sa.Column("event_id", sa.String(32), primary_key=True),
            sa.Column("user_id", sa.String(32), sa.ForeignKey("user.user_id"), nullable=False),
            sa.Column("role", sa.String(8), nullable=False),
            sa.Column("session_id", sa.String(64), nullable=True),
            sa.Column("event_type", sa.String(32), nullable=False),
            sa.Column("scenario", sa.String(64), nullable=True),
            sa.Column("result_state", sa.String(32), nullable=True),
            sa.Column("need_human", sa.Boolean(), nullable=True),
            sa.Column("authority_verified", sa.Boolean(), nullable=True),
            sa.Column("grounding_passed", sa.Boolean(), nullable=True),
            sa.Column("latency_first_token_ms", sa.Integer(), nullable=True),
            sa.Column("latency_total_ms", sa.Integer(), nullable=True),
            sa.Column("is_trial", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    existing = {item["name"] for item in sa.inspect(bind).get_indexes("trial_usage_event")}
    for column in ("user_id", "session_id", "event_type", "scenario", "is_trial"):
        name = f"ix_trial_usage_event_{column}"
        if name not in existing:
            op.create_index(name, "trial_usage_event", [column])
    if not sa.inspect(bind).has_table("trial_benchmark_record"):
        op.create_table(
            "trial_benchmark_record",
            sa.Column("record_id", sa.String(32), primary_key=True),
            sa.Column("scenario", sa.String(64), nullable=False),
            sa.Column("participant_id_hash", sa.String(64), nullable=False),
            sa.Column("manual_duration_seconds", sa.Float(), nullable=False),
            sa.Column("ai_duration_seconds", sa.Float(), nullable=False),
            sa.Column("manual_success", sa.Boolean(), nullable=False),
            sa.Column("ai_success", sa.Boolean(), nullable=False),
            sa.Column("manual_source_found", sa.Boolean(), nullable=False),
            sa.Column("ai_source_found", sa.Boolean(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    existing = {item["name"] for item in sa.inspect(bind).get_indexes("trial_benchmark_record")}
    for column in ("scenario", "participant_id_hash"):
        name = f"ix_trial_benchmark_record_{column}"
        if name not in existing:
            op.create_index(name, "trial_benchmark_record", [column])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("trial_benchmark_record"):
        op.drop_table("trial_benchmark_record")
    if inspector.has_table("trial_usage_event"):
        op.drop_table("trial_usage_event")
