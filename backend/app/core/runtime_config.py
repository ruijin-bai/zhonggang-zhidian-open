"""Runtime model configuration cache.

Adapters are constructed synchronously inside services, but the persisted
``ModelConfig`` lives in an async SQLAlchemy DB. To avoid async/sync tangling,
the async layer (router / startup) reads the DB and pushes the active config
into this module-level cache, which the synchronous adapter factories consult.
On every config change the cache is refreshed and the adapter factories are
reset (``lru_cache.clear``), so no backend restart is needed.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RuntimeModelConfig:
    enabled: bool = False
    # LLM
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout: float = 45.0
    # Embedding
    embed_base_url: str = ""
    embed_api_key: str = ""
    embed_model: str = ""
    embed_dim: int = 1024


_RUNTIME: RuntimeModelConfig | None = None


def get_runtime_model_config() -> RuntimeModelConfig | None:
    """Return the currently active runtime config, or None to fall back to .env."""
    return _RUNTIME


def set_runtime_model_config(cfg: RuntimeModelConfig | None) -> None:
    """Replace the active runtime config (called after DB save / on startup)."""
    global _RUNTIME
    _RUNTIME = cfg


def mask_secret(value: str) -> str:
    """Mask a secret for safe frontend display: keep first 4 + last 4 chars."""
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-4:]
