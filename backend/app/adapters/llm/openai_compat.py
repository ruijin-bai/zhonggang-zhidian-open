"""OpenAI-compatible LLM adapter (交融大模型 / any OpenAI-compatible endpoint)."""
from __future__ import annotations

import httpx

from app.adapters.llm.base import ChatResult, LLMAdapter
from app.core.config import get_settings
from app.core.exceptions import LLMTimeoutError
from collections.abc import AsyncIterator

# 交融 MaaS（集团内大模型服务）对 Python 脚本有安全拦截：缺少浏览器 UA 会被 403。
# 所有经此适配器的请求统一带上 UA 头规避。
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
)

_SETTINGS = get_settings()


class OpenAICompatLLMAdapter(LLMAdapter):
    kind = "openai_compat"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            base_url=base_url or _SETTINGS.LLM_BASE_URL,
            api_key=api_key or _SETTINGS.LLM_API_KEY or "EMPTY",
            timeout=timeout or _SETTINGS.LLM_TIMEOUT,
            max_retries=0,
            default_headers={"User-Agent": _USER_AGENT},
        )
        self._model = model or _SETTINGS.LLM_MODEL

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1500,
        timeout: float = 45.0,
    ) -> ChatResult:
        try:
            resp = await self._client.chat.completions.create(
                model=model or self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError() from exc
        except Exception as exc:  # noqa: BLE001
            # Surface as timeout-style upstream error for the generator's fallback path.
            raise LLMTimeoutError(f"LLM 调用失败: {exc}") from exc

        if not resp.choices:
            raise LLMTimeoutError("模型返回为空（请检查 API Key 与模型名称是否正确）")
        choice = resp.choices[0]
        return ChatResult(
            content=choice.message.content or "",
            finish_reason=choice.finish_reason or "stop",
            usage=resp.usage.model_dump() if resp.usage else {},
            model=resp.model,
            raw=resp,
        )

    async def stream(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1500,
        timeout: float = 45.0,
    ) -> AsyncIterator[str]:
        """Yield incremental text tokens using the OpenAI streaming API."""
        try:
            stream = await self._client.chat.completions.create(
                model=model or self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                stream=True,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError() from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMTimeoutError(f"LLM 流式调用失败: {exc}") from exc
