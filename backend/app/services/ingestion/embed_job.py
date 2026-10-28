"""Vectorisation job (RQ task + synchronous runner) for clause embeddings."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.embedding.factory import get_embedding_adapter
from app.db.models.clause import Clause

# 超长条款会超过 embedding 模型的 token 上限（如 34780 字的整节），嵌入时截断到
# 语义足够的前缀；全文仍保留在 content 供 BM25 精确检索与原文展示。
_MAX_EMBED_CHARS = 2000


def _truncate(text: str) -> str:
    return text if len(text) <= _MAX_EMBED_CHARS else text[: _MAX_EMBED_CHARS]


async def embed_pending_clauses(session: AsyncSession, batch_size: int = 50) -> int:
    """Compute and persist embeddings for clauses that lack one, in batches.

    Batching avoids a single oversized embedding request (large legacy .doc
    re-ingestions can add hundreds of clauses at once, which would time out the
    provider). Returns the number of clauses embedded.
    """
    adapter = get_embedding_adapter()
    result = await session.execute(select(Clause).where(Clause.embedding.is_(None)))
    clauses = list(result.scalars().all())
    if not clauses:
        return 0
    n = 0
    for i in range(0, len(clauses), batch_size):
        batch = clauses[i : i + batch_size]
        texts = [f"{c.clause_no} {_truncate(c.content)}" for c in batch]
        vectors = adapter.embed(texts)
        for clause, vec in zip(batch, vectors):
            clause.embedding = vec
        n += len(batch)
        await session.flush()
    # A long-running SQLite/API process may already hold the normalized matrix.
    # Force the next retrieval to rebuild it after the surrounding transaction
    # commits instead of serving stale vectors.
    from app.services.rag.retriever import reset_memory_vector_cache

    reset_memory_vector_cache()
    return n
