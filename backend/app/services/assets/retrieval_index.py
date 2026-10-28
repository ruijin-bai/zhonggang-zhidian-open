"""Rebuildable vector index for governed V2 retrieval units."""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.adapters.embedding.factory import get_embedding_adapter
from app.core.config import get_settings
from app.core.runtime_config import get_runtime_model_config
from app.db.base import gen_id
from app.db.models.asset import (
    AssetVersion,
    AssetVersionDocument,
    ContentNode,
    DocumentParseRun,
    KnowledgeAsset,
    RetrievalEmbedding,
    RetrievalUnit,
    RetrievalUnitSource,
)


# Only released business evidence enters employee QA. Draft history, review
# opinions, training copies and raw design resources remain browsable assets but
# are never silently promoted to authoritative answer material.
QA_DOCUMENT_ROLES = frozenset({
    "normative_body",
    "normative_annex",
    "standard_table",
    "flowchart",
    "form",
    "template",
    "implementation_guide",
})


@dataclass(frozen=True)
class EmbeddingSpec:
    model_key: str
    dimension: int


def active_embedding_spec() -> EmbeddingSpec:
    adapter = get_embedding_adapter()
    runtime = get_runtime_model_config()
    settings = get_settings()
    model_key = (
        runtime.embed_model
        if runtime is not None and runtime.enabled and runtime.embed_model
        else settings.EMBED_MODEL
    )
    return EmbeddingSpec(model_key=model_key[:128], dimension=int(getattr(adapter, "dim", settings.EMBED_DIM)))


def retrieval_input(asset_title: str, unit: RetrievalUnit) -> str:
    return "\n".join(part for part in (asset_title.strip(), unit.title.strip(), unit.text.strip()) if part)


def retrieval_input_hash(asset_title: str, unit: RetrievalUnit) -> str:
    return hashlib.sha256(retrieval_input(asset_title, unit).encode("utf-8")).hexdigest()


def eligible_unit_predicates(today: date | None = None) -> tuple:
    today = today or date.today()
    return (
        RetrievalUnit.status == "verified",
        KnowledgeAsset.status == "active",
        AssetVersion.release_state == "current",
        AssetVersion.ingestion_state == "ready",
        or_(AssetVersion.effective_date.is_(None), AssetVersion.effective_date <= today),
        or_(AssetVersion.expiry_date.is_(None), AssetVersion.expiry_date >= today),
        DocumentParseRun.is_current.is_(True),
        DocumentParseRun.status == "succeeded",
        AssetVersionDocument.role.in_(QA_DOCUMENT_ROLES),
    )


async def build_retrieval_embeddings(
    session: AsyncSession,
    *,
    batch_size: int = 16,
    concurrency: int = 1,
    force: bool = False,
    limit: int | None = None,
) -> dict:
    """Embed eligible V2 units and checkpoint every successful batch."""
    adapter = get_embedding_adapter()
    if getattr(adapter, "kind", "") == "mock":
        raise RuntimeError("未配置真实向量模型，拒绝以 mock 向量建立问答索引")
    spec = active_embedding_spec()
    stmt = (
        select(RetrievalUnit, KnowledgeAsset.title)
        .join(AssetVersion, AssetVersion.version_id == RetrievalUnit.version_id)
        .join(KnowledgeAsset, KnowledgeAsset.asset_id == AssetVersion.asset_id)
        .join(RetrievalUnitSource, RetrievalUnitSource.unit_id == RetrievalUnit.unit_id)
        .join(ContentNode, ContentNode.node_id == RetrievalUnitSource.node_id)
        .join(DocumentParseRun, DocumentParseRun.parse_run_id == ContentNode.parse_run_id)
        .join(
            AssetVersionDocument,
            (AssetVersionDocument.version_id == AssetVersion.version_id)
            & (AssetVersionDocument.document_id == ContentNode.document_id),
        )
        .where(*eligible_unit_predicates())
        .order_by(RetrievalUnit.unit_id)
    )
    rows = list((await session.execute(stmt)).all())
    # A future multi-source unit may join more than once; embedding identity is
    # still the unit, not the number of source links.
    unique: dict[str, tuple[RetrievalUnit, str]] = {}
    for unit, asset_title in rows:
        unique.setdefault(unit.unit_id, (unit, asset_title or ""))

    existing_rows = list((await session.execute(
        select(RetrievalEmbedding).options(defer(RetrievalEmbedding.vector)).where(
            RetrievalEmbedding.model_key == spec.model_key,
            RetrievalEmbedding.unit_id.in_(list(unique) or ["__none__"]),
        )
    )).scalars())
    existing = {item.unit_id: item for item in existing_rows}
    pending: list[tuple[RetrievalUnit, str, str]] = []
    already_ready = 0
    for unit, asset_title in unique.values():
        input_hash = retrieval_input_hash(asset_title, unit)
        current = existing.get(unit.unit_id)
        if force or current is None or current.status != "ready" or current.content_hash != input_hash:
            pending.append((unit, asset_title, input_hash))
        else:
            already_ready += 1
    if limit is not None:
        pending = pending[: max(0, limit)]

    indexed = 0
    failed = 0
    groups: dict[str, list[tuple[RetrievalUnit, str, str]]] = {}
    for item in pending:
        groups.setdefault(item[2], []).append(item)

    touched_embeddings: list[RetrievalEmbedding] = []

    def persist_group(input_hash: str, vector: list[float]) -> int:
        written = 0
        for unit, _title, _ in groups[input_hash]:
            item = existing.get(unit.unit_id)
            if item is None:
                item = RetrievalEmbedding(
                    embedding_id=gen_id("uemb"),
                    unit_id=unit.unit_id,
                    model_key=spec.model_key,
                    dimension=spec.dimension,
                    content_hash=input_hash,
                )
                session.add(item)
                existing[unit.unit_id] = item
            item.dimension = spec.dimension
            item.vector = vector
            item.content_hash = input_hash
            item.status = "ready"
            touched_embeddings.append(item)
            written += 1
        return written

    representatives = [items[0] for items in groups.values()]
    batches = [
        representatives[offset : offset + max(1, batch_size)]
        for offset in range(0, len(representatives), max(1, batch_size))
    ]
    wave_size = max(1, concurrency)
    for wave_offset in range(0, len(batches), wave_size):
        wave = batches[wave_offset : wave_offset + wave_size]
        calls = [
            asyncio.to_thread(adapter.embed, [retrieval_input(title, unit) for unit, title, _ in batch])
            for batch in wave
        ]
        try:
            wave_results = await asyncio.gather(*calls)
            for batch, vectors in zip(wave, wave_results, strict=True):
                if len(vectors) != len(batch):
                    raise RuntimeError("向量服务返回数量与输入不一致")
                for (unit, _title, input_hash), vector in zip(batch, vectors, strict=True):
                    if len(vector) != spec.dimension:
                        raise RuntimeError(
                            f"向量维度不一致: unit={unit.unit_id}, expected={spec.dimension}, actual={len(vector)}"
                        )
                    indexed += persist_group(input_hash, vector)
            await session.commit()
            # ORM instances remain useful as lightweight identity metadata for
            # resumability, but 4096-d Python float lists must not accumulate
            # for the lifetime of a multi-hour indexing job.
            for item in touched_embeddings:
                session.expire(item, ["vector"])
            touched_embeddings.clear()
        except Exception:
            await session.rollback()
            failed += sum(len(batch) for batch in wave)
            raise

    try:
        from app.services.rag.retriever import reset_compound_vector_cache

        reset_compound_vector_cache()
    except ImportError:
        pass
    return {
        "model_key": spec.model_key,
        "dimension": spec.dimension,
        "eligible": len(unique),
        "pending": len(pending),
        "provider_inputs": len(representatives),
        "indexed": indexed,
        "failed": failed,
        "ready": already_ready + indexed,
    }
