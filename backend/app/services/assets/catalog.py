"""Shared counts for current, source-backed content visible to a reader."""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.asset import (
    AssetDocument, AssetVersion, AssetVersionDocument, ContentNode,
    DocumentParseRun, KnowledgeAsset, RetrievalUnit, RetrievalUnitSource,
)
from app.services.assets.publication import asset_filter
from app.services.assets.retrieval_index import eligible_unit_predicates
from app.services.permission.rbac import build_asset_filter


async def readable_version_unit_counts(
    db: AsyncSession, user, permissions, version_ids: Sequence[str] | None = None,
) -> dict[str, int]:
    """Count each readable unit once even when it has several source nodes."""
    if version_ids is not None and not version_ids:
        return {}
    stmt = (
        select(RetrievalUnit.version_id, func.count(func.distinct(RetrievalUnit.unit_id)))
        .join(AssetVersion, AssetVersion.version_id == RetrievalUnit.version_id)
        .join(KnowledgeAsset, KnowledgeAsset.asset_id == AssetVersion.asset_id)
        .join(RetrievalUnitSource, RetrievalUnitSource.unit_id == RetrievalUnit.unit_id)
        .join(ContentNode, ContentNode.node_id == RetrievalUnitSource.node_id)
        .join(DocumentParseRun, DocumentParseRun.parse_run_id == ContentNode.parse_run_id)
        .join(AssetDocument, AssetDocument.document_id == ContentNode.document_id)
        .join(AssetVersionDocument, (AssetVersionDocument.version_id == AssetVersion.version_id)
              & (AssetVersionDocument.document_id == AssetDocument.document_id))
        .where(
            *eligible_unit_predicates(), asset_filter(user, permissions, document=True),
            build_asset_filter(user, permissions, secret_level=KnowledgeAsset.secret_level,
                org_path=KnowledgeAsset.org_path, domain=KnowledgeAsset.domain,
                content_secret_level=RetrievalUnit.secret_level),
        )
        .group_by(RetrievalUnit.version_id)
    )
    if version_ids is not None:
        stmt = stmt.where(RetrievalUnit.version_id.in_(version_ids))
    return {version_id: int(count) for version_id, count in (await db.execute(stmt)).all()}
