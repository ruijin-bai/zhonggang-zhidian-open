"""V2 compound-unit indexing, gating and retrieval regression tests."""
from __future__ import annotations

import hashlib

from sqlalchemy import func, select

from app.adapters.embedding.factory import get_embedding_adapter
from app.db.models.asset import (
    AssetDocument,
    AssetVersion,
    AssetVersionDocument,
    CitationSpan,
    ContentNode,
    DocumentParseRun,
    KnowledgeAsset,
    RetrievalEmbedding,
    RetrievalUnit,
    RetrievalUnitSource,
)
from app.db.models.permission import Permission
from app.db.models.user import User
from app.services.assets.parse_service import _retrieval_segments
from app.services.assets.retrieval_index import build_retrieval_embeddings
from app.services.rag.retriever import RetrieverService, reset_compound_vector_cache


def test_oversized_node_segments_are_bounded_and_source_addressable():
    text = ("本条规定适用于境外项目审批；" * 200) + "结束。"
    segments = _retrieval_segments(text, max_chars=300, overlap=30)
    assert len(segments) > 1
    assert all(len(chunk) <= 300 for _, _, chunk in segments)
    assert all(text[start:end] == chunk for start, end, chunk in segments)
    assert segments[0][0] == 0
    assert segments[-1][1] == len(text)


async def _seed_compound_unit(session, *, secret_level: str = "internal"):
    asset = KnowledgeAsset(
        asset_type="management_method",
        title="境外项目审批管理办法",
        business_code="CHEC-PM-001",
        org_path="/",
        secret_level=secret_level,
        domain="境外项目",
        status="active",
    )
    session.add(asset)
    await session.flush()
    version = AssetVersion(
        asset_id=asset.asset_id,
        version_label="v2",
        release_state="current",
        ingestion_state="ready",
        issue_no="CHEC-PM-001",
    )
    document = AssetDocument(
        filename="审批办法.docx",
        title="审批办法正文",
        mime="application/docx",
        object_key="local://approval.docx",
        sha256="a" * 64,
        size_bytes=100,
        secret_level=secret_level,
        parse_disposition="structured",
    )
    session.add_all([version, document])
    await session.flush()
    link = AssetVersionDocument(
        version_id=version.version_id,
        document_id=document.document_id,
        role="normative_body",
        mandatory=True,
        normative=True,
    )
    run = DocumentParseRun(
        document_id=document.document_id,
        parser_name="test",
        status="succeeded",
        is_current=True,
        source_hash="b" * 64,
    )
    session.add_all([link, run])
    await session.flush()
    text = "境外项目单笔变更超过五十万美元的，应报总部审批。"
    node = ContentNode(
        parse_run_id=run.parse_run_id,
        document_id=document.document_id,
        node_type="article",
        order_path="0001",
        ordinal=1,
        label="第十二条",
        title="变更审批",
        text=text,
        normalized_text=text,
        source_page=3,
        source_locator="page:3/article:12",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    session.add(node)
    await session.flush()
    span = CitationSpan(
        node_id=node.node_id,
        start_offset=0,
        end_offset=len(text),
        quote_text=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    unit = RetrievalUnit(
        version_id=version.version_id,
        unit_type="article",
        title="第十二条 变更审批",
        text=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        secret_level=secret_level,
        status="verified",
    )
    session.add_all([span, unit])
    await session.flush()
    session.add(RetrievalUnitSource(unit_id=unit.unit_id, node_id=node.node_id, span_id=span.span_id))
    await session.flush()
    return unit, asset


async def test_compound_unit_is_retrieved_and_keeps_v2_identity(session):
    unit, _asset = await _seed_compound_unit(session)
    adapter = get_embedding_adapter()
    vector = adapter.embed(["境外项目单笔变更超过五十万美元的，应报总部审批。"])[0]
    session.add(RetrievalEmbedding(
        unit_id=unit.unit_id,
        model_key="text-embedding-3-small",
        dimension=len(vector),
        vector=vector,
        content_hash=unit.content_hash,
        status="ready",
    ))
    await session.flush()
    reset_compound_vector_cache()
    user = User(user_id="u_v2", role="R4", secret_clearance="secret")
    perm = Permission(role="R4", org_scope="/", secret_level="secret", domain="*")

    results = await RetrieverService().retrieve(
        session, user, [perm], "境外项目变更款由谁审批", top_k=3, min_score=0.0
    )
    assert results
    assert results[0].clause.clause_id == unit.unit_id
    assert results[0].source_kind == "compound_unit"
    assert results[0].source_metadata["source_locator"] == "page:3/article:12"


async def test_compound_rbac_blocks_content_above_permission_ceiling(session):
    await _seed_compound_unit(session, secret_level="confidential")
    user = User(user_id="u_v2_rbac", role="R1", secret_clearance="secret")
    perm = Permission(role="R1", org_scope="/", secret_level="internal", domain="*")
    results = await RetrieverService().retrieve(
        session, user, [perm], "境外项目变更审批", top_k=3, min_score=0.0
    )
    assert results == []


async def test_compound_embedding_index_is_incremental(session, monkeypatch):
    await _seed_compound_unit(session)

    class RealLikeAdapter:
        kind = "openai_compat"
        dim = 128

        @staticmethod
        def embed(texts):
            return get_embedding_adapter().embed(texts)

    monkeypatch.setattr(
        "app.services.assets.retrieval_index.get_embedding_adapter", lambda: RealLikeAdapter()
    )
    first = await build_retrieval_embeddings(session, batch_size=2)
    second = await build_retrieval_embeddings(session, batch_size=2)
    count = int((await session.execute(select(func.count()).select_from(RetrievalEmbedding))).scalar_one())
    assert first["indexed"] == 1
    assert second["indexed"] == 0
    assert second["ready"] == 1
    assert count == 1
