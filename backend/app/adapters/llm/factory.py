"""Factory selecting the LLM adapter implementation from configuration."""
from __future__ import annotations

from functools import lru_cache

from app.adapters.llm.base import LLMAdapter
from app.adapters.llm.mock import MockLLMAdapter
from app.adapters.llm.openai_compat import OpenAICompatLLMAdapter
from app.core.config import get_settings
from app.core.runtime_config import get_runtime_model_config

_SETTINGS = get_settings()


@lru_cache
def get_llm_adapter(fast: bool = False) -> LLMAdapter:
    """Return the configured LLM adapter.

    Priority: runtime-configured real provider (set from the frontend model
    config) > .env ``openai_compat`` settings > mock (no key required).

    ``fast=True`` 返回快速模型（``QA_FAST_MODEL``，如 deepseek-v4-flash），
    供 query 改写 / 自省评估 / 矛盾检测等时延敏感的辅助步骤使用；仅最终
    生成沿用强模型（kimi-k2.6），兼顾速度与回答质量。
    """
    rt = get_runtime_model_config()
    if rt is not None:
        if not rt.enabled:
            return MockLLMAdapter()
        if rt.llm_api_key:
            model = _SETTINGS.QA_FAST_MODEL if fast else rt.llm_model
            return OpenAICompatLLMAdapter(
                base_url=rt.llm_base_url,
                api_key=rt.llm_api_key,
                model=model,
                timeout=rt.llm_timeout,
            )
    if _SETTINGS.LLM_PROVIDER == "openai_compat" and _SETTINGS.LLM_API_KEY:
        return OpenAICompatLLMAdapter()
    return MockLLMAdapter()


def reset_llm_adapter() -> None:
    get_llm_adapter.cache_clear()
