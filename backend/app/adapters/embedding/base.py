"""Embedding adapter contract (architecture §7.4)."""
from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingAdapter(ABC):
    """Abstract text-embedding adapter."""

    kind: str = "base"
    dim: int = 128

    @abstractmethod
    def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        """Return a list of embedding vectors (one per input text)."""
        raise NotImplementedError
