"""Reranker adapter contract (architecture §6 T07+).

专门 cross-encoder 精排模型对 (query, document) 的相关性打分远比通用 LLM 提示词
精确。适配器返回 ``[(document_index, relevance_score)]``（按相关性降序）；检索器
据此把 index 映射回候选条款，并在无 reranker 时降级回 LLM 打分路径。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class RerankerAdapter(ABC):
    """Abstract reranker adapter scoring documents against a query."""

    kind: str = "base"

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[tuple[int, float]]:
        """Return ``[(document_index, relevance_score)]`` sorted by descending score."""
        raise NotImplementedError
