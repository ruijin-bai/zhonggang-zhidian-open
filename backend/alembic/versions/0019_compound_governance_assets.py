"""compound governance asset V2 foundation

Revision ID: 0019
Revises: 0018
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

from app.db.base import Base
from app.db import models as _models  # noqa: F401 - register V2 tables


revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


_TABLE_NAMES = [
    "knowledge_asset",
    "release_event",
    "asset_document",
    "asset_version",
    "asset_version_document",
    "asset_relation_v2",
    "document_relation",
    "document_parse_run",
    "content_node",
    "citation_span",
    "retrieval_unit",
    "retrieval_unit_source",
    "retrieval_embedding",
    "knowledge_assertion",
    "assertion_evidence",
    "legacy_asset_mapping",
]


def upgrade() -> None:
    """Create only V2 tables, preserving all V1 regulation and clause data."""
    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in _TABLE_NAMES]
    Base.metadata.create_all(bind=bind, tables=tables, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for name in reversed(_TABLE_NAMES):
        if inspector.has_table(name):
            Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
