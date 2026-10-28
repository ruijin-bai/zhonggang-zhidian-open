"""OpenAI-compatible reranker adapter (交融 qwen3 reranker via ``/rerank`` endpoint).

交融 MaaS 对 Python 脚本有安全拦截：缺少浏览器 UA 会被 403，统一带上 UA。
reranker 以 cross-encoder ``/rerank`` 接口暴露（Jina/vLLM 约定）：请求体为
``query`` + ``documents``，响应体每项带 ``index`` + ``relevance_score``。任何
失败都以异常上抛，由 ``RetrieverService.rerank`` 捕获后降级到 LLM 打分，绝不让
重排阻塞主链路。
"""
from __future__ import annotations

import httpx

from app.adapters.reranker.base import RerankerAdapter
from app.core.config import get_settings

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
)

_SETTINGS = get_settings()


class OpenAICompatRerankerAdapter(RerankerAdapter):
    kind = "openai_compat"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._base_url = (base_url or _SETTINGS.RERANK_BASE_URL).rstrip("/")
        self._api_key = api_key or _SETTINGS.RERANK_API_KEY or "EMPTY"
        self._model = model or _SETTINGS.RERANK_MODEL
        self._timeout = timeout or _SETTINGS.RERANK_TIMEOUT

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[tuple[int, float]]:
        """Score ``documents`` against ``query`` and return (index, score) pairs."""
        if not documents:
            return []
        url = f"{self._base_url}/rerank"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        }
        payload = {
            "model": self._model,
            "query": query,
            "documents": documents,
            "top_n": top_n or len(documents),
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        # 兼容 ``results``（Jina/vLLM）与 ``data``（部分网关）两种返回结构。
        results = data.get("results") or data.get("data") or []
        out: list[tuple[int, float]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            score = item.get("relevance_score")
            if score is None:
                score = item.get("score")
            if idx is None or score is None:
                continue
            try:
                out.append((int(idx), float(score)))
            except (TypeError, ValueError):
                continue
        return out
