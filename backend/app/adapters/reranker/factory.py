"""Factory selecting the reranker adapter from configuration."""
from __future__ import annotations

from functools import lru_cache

from app.adapters.reranker.base import RerankerAdapter
from app.adapters.reranker.openai_compat import OpenAICompatRerankerAdapter
from app.core.config import get_settings
from app.core.runtime_config import get_runtime_model_config

_SETTINGS = get_settings()


@lru_cache
def get_reranker_adapter() -> RerankerAdapter | None:
    """Return the configured reranker, or ``None`` when disabled / unconfigured.

    reranker 与 LLM 同属交融 MaaS 平台，复用同一 base_url 与 api_key。key 优先
    取运行时配置（前端在 DB 里保存的真实 key），回退 .env 静态配置；无 key
    （mock / 本地 / CI）时返回 ``None``，由 ``RetrieverService.rerank`` 透明降级
    到 LLM 打分路径。
    """
    if not _SETTINGS.RERANK_ENABLED:
        return None
    rt = get_runtime_model_config()
    api_key = _SETTINGS.RERANK_API_KEY
    base_url = _SETTINGS.RERANK_BASE_URL
    if rt is not None:
        api_key = api_key or rt.llm_api_key
        base_url = rt.llm_base_url or base_url
    if not api_key:
        api_key = _SETTINGS.LLM_API_KEY
    if not api_key:
        return None
    return OpenAICompatRerankerAdapter(base_url=base_url, api_key=api_key)


def reset_reranker_adapter() -> None:
    get_reranker_adapter.cache_clear()
