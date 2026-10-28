"""OpenAI-compatible embedding adapter (交融 embedding / any OpenAI-compatible)."""
from __future__ import annotations

from app.adapters.embedding.base import EmbeddingAdapter
from app.core.config import get_settings
from app.core.exceptions import EmbeddingError

# 交融 MaaS 对 Python 脚本有安全拦截：缺少浏览器 UA 会被 403。
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
)

_SETTINGS = get_settings()


class OpenAICompatEmbeddingAdapter(EmbeddingAdapter):
    kind = "openai_compat"
    dim = _SETTINGS.EMBED_DIM

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        dim: int | None = None,
    ) -> None:
        # The EmbeddingAdapter contract requires a *synchronous* ``embed`` because
        # the retriever calls it inline. Use the synchronous OpenAI client here.
        from openai import OpenAI

        self._client = OpenAI(
            base_url=base_url or _SETTINGS.EMBED_BASE_URL,
            api_key=api_key or _SETTINGS.EMBED_API_KEY or "EMPTY",
            timeout=20.0,
            max_retries=1,
            default_headers={"User-Agent": _USER_AGENT},
        )
        self._model = model or _SETTINGS.EMBED_MODEL
        if dim is not None:
            self.dim = dim

    def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        try:
            resp = self._client.embeddings.create(model=model or self._model, input=texts)
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(f"向量化失败: {exc}") from exc
        return [item.embedding for item in resp.data]
