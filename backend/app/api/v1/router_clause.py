"""Clause detail endpoint — canonical path (architecture §3.2 ②).

Exposes ``GET /api/v1/clauses/{clause_id}`` consumed by the frontend
原文溯源 (source-tracing) page (``web/src/views/ClauseDetail.vue``).

The legacy ``GET /api/v1/regulations/clauses/{clause_id}`` route in
``router_regulation.py`` is intentionally kept for backwards compatibility and
is not modified by this change. Both routes return the identical
:class:`ClauseDetailOut` shape expected by the frontend.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_user_context
from app.core.exceptions import NotFoundError, ok
from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile
from app.db.models.qa import QASession, QACitation
from app.db.models.asset import (
    AssetDocument,
    AssetVersion,
    AssetVersionDocument,
    ContentNode,
    DocumentParseRun,
    KnowledgeAsset,
    RetrievalUnit,
    RetrievalUnitSource,
)
from app.db.session import get_db
from app.schemas.regulation import ClauseDetailOut
from app.services.assets.retrieval_index import eligible_unit_predicates
from app.services.permission.rbac import build_asset_filter, build_filter

router = APIRouter(prefix="/clauses", tags=["clauses"])


async def _historical_citation(db, clause_id, session_id, user, perms):
    """An owned citation can read its historical evidence under today's RBAC.

    Historical access never changes current retrieval eligibility. If an old
    record has no matching content hash, expose only its stored excerpt.
    """
    citation = (await db.execute(select(QACitation).join(QASession, QASession.session_id == QACitation.session_id).where(QACitation.session_id == session_id, QACitation.clause_id == clause_id, QASession.user_id == user.user_id))).scalars().first()
    if citation is None:
        raise NotFoundError("历史引用不存在或无权限")
    row = (await db.execute(select(Clause, RegulationFile).join(RegulationFile, Clause.file_id == RegulationFile.file_id).where(Clause.clause_id == clause_id, build_filter(user, perms, Clause.secret_level)))).first()
    if row is not None:
        clause, file = row
        matched = bool(citation.content_hash and citation.content_hash == clause.content_hash)
        historical = not matched or clause.status != "current" or file.status != "current" or bool(file.effective_date and file.effective_date > date.today()) or bool(file.expiry_date and file.expiry_date < date.today())
        return ok(ClauseDetailOut(clause_id=clause_id, file_id=file.file_id, clause_no=citation.clause_no, content=clause.content if matched else citation.excerpt, chapter=clause.chapter, secret_level=clause.secret_level, status=clause.status, source_page=citation.source_page, source_locator=clause.source_locator if matched else None, content_hash=citation.content_hash, file_title=citation.file_title, file_version=file.version, file_status=file.status, historical=historical, snapshot_only=not matched).model_dump())
    from app.services.rule.evidence import asset_source_statement
    row = (await db.execute(asset_source_statement(user, perms).where(RetrievalUnit.unit_id == clause_id))).first()
    if row is None:
        raise NotFoundError("历史来源已不存在或当前无权读取，请返回咨询记录查看当时引用")
    unit, version, asset, document, node, _link = row
    matched = bool(citation.content_hash and citation.content_hash == unit.content_hash)
    current = (await db.execute(asset_source_statement(user, perms).where(RetrievalUnit.unit_id == clause_id, *eligible_unit_predicates()))).first()
    historical = not matched or current is None
    return ok(ClauseDetailOut(clause_id=clause_id, file_id=asset.asset_id, clause_no=citation.clause_no, content=unit.text if matched else citation.excerpt, secret_level=unit.secret_level, status=unit.status, source_page=citation.source_page, source_locator=node.source_locator if matched else None, content_hash=citation.content_hash, file_title=citation.file_title, file_version=version.version_label, file_status=version.release_state, source_kind="asset", document_title=document.title, asset_version_id=version.version_id, historical=historical, snapshot_only=not matched).model_dump())


@router.get("/{clause_id}", response_model=None)
async def clause_detail(
    clause_id: str,
    session_id: str | None = None,
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    """Return the full detail of a single clause (原文溯源).

    Response shape matches :class:`ClauseDetailOut` and the fields consumed by
    ``ClauseDetail.vue``: ``file_title``, ``clause_no``, ``file_version``,
    ``file_status``, ``secret_level``, ``tags`` and ``content``.
    """
    user, perms = ctx
    if session_id:
        return await _historical_citation(db, clause_id, session_id, user, perms)
    stmt = (
        select(Clause, RegulationFile)
        .join(RegulationFile, Clause.file_id == RegulationFile.file_id)
        .where(
            Clause.clause_id == clause_id,
            Clause.status == "current",
            RegulationFile.status == "current",
            (RegulationFile.effective_date.is_(None) | (RegulationFile.effective_date <= date.today())),
            (RegulationFile.expiry_date.is_(None) | (RegulationFile.expiry_date >= date.today())),
            build_filter(user, perms, Clause.secret_level),
        )
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        compound_stmt = (
            select(
                RetrievalUnit,
                AssetVersion,
                KnowledgeAsset,
                AssetDocument,
                ContentNode,
                AssetVersionDocument,
            )
            .join(AssetVersion, AssetVersion.version_id == RetrievalUnit.version_id)
            .join(KnowledgeAsset, KnowledgeAsset.asset_id == AssetVersion.asset_id)
            .join(RetrievalUnitSource, RetrievalUnitSource.unit_id == RetrievalUnit.unit_id)
            .join(ContentNode, ContentNode.node_id == RetrievalUnitSource.node_id)
            .join(AssetDocument, AssetDocument.document_id == ContentNode.document_id)
            .join(DocumentParseRun, DocumentParseRun.parse_run_id == ContentNode.parse_run_id)
            .join(
                AssetVersionDocument,
                (AssetVersionDocument.version_id == AssetVersion.version_id)
                & (AssetVersionDocument.document_id == ContentNode.document_id),
            )
            .where(
                RetrievalUnit.unit_id == clause_id,
                *eligible_unit_predicates(),
                build_asset_filter(
                    user,
                    perms,
                    secret_level=KnowledgeAsset.secret_level,
                    content_secret_level=RetrievalUnit.secret_level,
                    org_path=KnowledgeAsset.org_path,
                    domain=KnowledgeAsset.domain,
                ),
                build_asset_filter(user, perms, secret_level=KnowledgeAsset.secret_level, content_secret_level=AssetDocument.secret_level, org_path=KnowledgeAsset.org_path, domain=KnowledgeAsset.domain),
            )
        )
        compound = (await db.execute(compound_stmt)).first()
        if compound is None:
            raise NotFoundError("检索单元不存在或无权限")
        unit, version, asset, document, node, link = compound
        label = unit.title or node.label or node.title or node.source_locator or unit.unit_type
        return ok(
            ClauseDetailOut(
                clause_id=unit.unit_id,
                file_id=asset.asset_id,
                chapter=node.title or None,
                clause_no=label[:64],
                content=unit.text,
                permission_level=None,
                secret_level=unit.secret_level,
                scenario_tags=[document.title, link.role, unit.unit_type],
                status="current",
                source_page=node.source_page,
                source_locator=node.source_locator,
                content_hash=unit.content_hash,
                file_title=asset.title,
                file_version=version.version_label,
                file_status=version.release_state,
                tags=[document.title, link.role, unit.unit_type],
                source_kind="asset", document_title=document.title, asset_version_id=version.version_id,
            ).model_dump()
        )
    clause, file = row
    return ok(
        ClauseDetailOut(
            clause_id=clause.clause_id,
            file_id=clause.file_id,
            chapter=clause.chapter,
            clause_no=clause.clause_no,
            content=clause.content,
            permission_level=clause.permission_level,
            secret_level=clause.secret_level,
            scenario_tags=clause.scenario_tags or [],
            status=clause.status,
            source_page=clause.source_page,
            source_locator=clause.source_locator,
            content_hash=clause.content_hash,
            file_title=file.title,
            file_version=file.version,
            file_status=file.status,
            tags=clause.scenario_tags or [],
        ).model_dump()
    )
