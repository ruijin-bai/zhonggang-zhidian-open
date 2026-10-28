"""Load the persisted model configuration into any process runtime."""
from __future__ import annotations

from sqlalchemy import select

from app.adapters.embedding.factory import reset_embedding_adapter
from app.adapters.llm.factory import reset_llm_adapter
from app.adapters.reranker.factory import reset_reranker_adapter
from app.core.runtime_config import RuntimeModelConfig, set_runtime_model_config
from app.core.secret_vault import decrypt_secret
from app.db.models.model_config import ModelConfig
from app.db.session import SessionLocal


async def load_runtime_model_config() -> ModelConfig | None:
    """Activate the DB-backed provider config in API, RQ and maintenance jobs."""
    async with SessionLocal() as session:
        row = (
            await session.execute(select(ModelConfig).where(ModelConfig.id == "singleton"))
        ).scalar_one_or_none()
        if row is None:
            set_runtime_model_config(None)
            return None
        set_runtime_model_config(
            RuntimeModelConfig(
                enabled=row.enabled,
                llm_base_url=row.llm_base_url,
                llm_api_key=decrypt_secret(row.llm_api_key),
                llm_model=row.llm_model,
                llm_timeout=row.llm_timeout,
                embed_base_url=row.embed_base_url,
                embed_api_key=decrypt_secret(row.embed_api_key),
                embed_model=row.embed_model,
                embed_dim=row.embed_dim,
            )
        )
    reset_llm_adapter()
    reset_embedding_adapter()
    reset_reranker_adapter()
    return row
