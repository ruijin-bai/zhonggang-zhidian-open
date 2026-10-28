"""Deterministic mock embedding adapter (no API key required).

Uses a hashing trick over Chinese character unigrams/bigrams and latin tokens,
with TF weighting and L2 normalisation. This yields stable, reproducible vectors
so that clauses sharing terminology end up close in cosine space — enough to
drive retrieval correctly in local / CI environments.
"""
from __future__ import annotations

import hashlib
import math
import re

from app.adapters.embedding.base import EmbeddingAdapter
from app.core.config import get_settings

_SETTINGS = get_settings()


def _tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    tokens: list[str] = re.findall(r"[a-z0-9]+", text)
    cjk = re.findall(r"[一-鿿]", text)
    for i, ch in enumerate(cjk):
        tokens.append(f"c:{ch}")
        if i + 1 < len(cjk):
            tokens.append(f"b:{cjk[i]}{cjk[i + 1]}")
    return tokens


class MockEmbeddingAdapter(EmbeddingAdapter):
    kind = "mock"
    dim = _SETTINGS.EMBED_DIM

    def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        dim = self.dim
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * dim
            for tok in _tokenize(text):
                h = hashlib.md5(tok.encode("utf-8")).digest()
                idx = int.from_bytes(h[:4], "big") % dim
                # Weight by sign of a second hash to spread signal.
                sign = 1.0 if h[4] % 2 == 0 else -1.0
                vec[idx] += sign
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            out.append(vec)
        return out
