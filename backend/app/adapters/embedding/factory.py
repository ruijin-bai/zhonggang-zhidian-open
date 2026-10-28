"""Factory selecting the embedding adapter from configuration."""
from __future__ import annotations

from functools import lru_cache

from app.adapters.embedding.base import EmbeddingAdapter
from app.adapters.embedding.mock import MockEmbeddingAdapter
from app.adapters.embedding.openai_compat import OpenAICompatEmbeddingAdapter
from app.core.config import get_settings
from app.core.runtime_config import get_runtime_model_config

_SETTINGS = get_settings()


@lru_cache
def get_embedding_adapter() -> EmbeddingAdapter:
    """Return the configured embedding adapter.

    Priority: runtime-configured real provider (set from the frontend model
    config) > .env ``openai_compat`` settings > mock (no key required).
    """
    rt = get_runtime_model_config()
    if rt is not None:
        if not rt.enabled:
            return MockEmbeddingAdapter()
        if rt.embed_api_key:
            return OpenAICompatEmbeddingAdapter(
                base_url=rt.embed_base_url,
                api_key=rt.embed_api_key,
                model=rt.embed_model,
                dim=rt.embed_dim,
            )
    if _SETTINGS.EMBED_PROVIDER == "openai_compat" and _SETTINGS.EMBED_API_KEY:
        return OpenAICompatEmbeddingAdapter()
    return MockEmbeddingAdapter()


def reset_embedding_adapter() -> None:
    get_embedding_adapter.cache_clear()
