"""System endpoints: runtime model configuration (LLM + Embedding).

白总偏好：模型名称 / API 地址 / API key 由管理员在前端自助配置，密钥落地
服务端数据库、前端脱敏不回显明文。配置变更后热生效，无需重启后端。
"""
from __future__ import annotations

from pydantic import BaseModel

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.embedding.openai_compat import OpenAICompatEmbeddingAdapter
from app.adapters.embedding.factory import reset_embedding_adapter
from app.adapters.llm.factory import reset_llm_adapter
from app.adapters.reranker.factory import reset_reranker_adapter
from app.adapters.llm.openai_compat import OpenAICompatLLMAdapter
from app.api.v1.deps import require_roles
from app.api.v1.deps import get_current_user
from app.core.config import get_settings
from app.core.exceptions import BadRequestError, ok
from app.core.runtime_config import RuntimeModelConfig, mask_secret, set_runtime_model_config
from app.core.secret_vault import decrypt_secret, encrypt_secret
from app.db.models.model_config import ModelConfig
from app.db.session import get_db

router = APIRouter(prefix="/system", tags=["system"])

# 交融 MaaS 默认兼容地址
DEFAULT_BASE_URL = "https://c4ai.ccccltd.cn/api/compatible/v1"
SINGLETON_ID = "singleton"
settings = get_settings()


@router.get("/competition-capabilities")
async def competition_capabilities(_: object = Depends(get_current_user)):
    """Expose only safe feature flags; no credentials or model details."""
    return ok({"competition_demo_enabled": settings.COMPETITION_DEMO_ENABLED})


class ModelConfigIn(BaseModel):
    enabled: bool = True
    llm_base_url: str = ""
    llm_api_key: str = ""  # 留空表示不修改（保留已有密钥）
    llm_model: str = ""
    # None means "keep the persisted value". The web form historically omitted
    # this field, which silently reset every save to 8 seconds.
    llm_timeout: float | None = None
    embed_base_url: str = ""
    embed_api_key: str = ""  # 留空表示不修改
    embed_model: str = ""
    embed_dim: int = 1024


def _mask_row(row: ModelConfig) -> dict:
    return {
        "enabled": row.enabled,
        "llm_base_url": row.llm_base_url,
        "llm_api_key": mask_secret(decrypt_secret(row.llm_api_key)),
        "llm_model": row.llm_model,
        "llm_timeout": row.llm_timeout,
        "embed_base_url": row.embed_base_url,
        "embed_api_key": mask_secret(decrypt_secret(row.embed_api_key)),
        "embed_model": row.embed_model,
        "embed_dim": row.embed_dim,
    }


def _default_payload() -> dict:
    return {
        "enabled": False,
        "llm_base_url": DEFAULT_BASE_URL,
        "llm_api_key": "",
        "llm_model": "",
        "llm_timeout": 45.0,
        "embed_base_url": DEFAULT_BASE_URL,
        "embed_api_key": "",
        "embed_model": "",
        "embed_dim": 1024,
    }


def _resolve_candidate(payload: ModelConfigIn, stored: ModelConfig | None) -> dict:
    """Build a candidate without mutating the currently active configuration."""
    return {
        "llm_base_url": payload.llm_base_url or (stored.llm_base_url if stored else "") or DEFAULT_BASE_URL,
        "llm_api_key": payload.llm_api_key or (decrypt_secret(stored.llm_api_key) if stored else ""),
        "llm_model": payload.llm_model or (stored.llm_model if stored else "") or "jiaorong-deepseek-v4-flash",
        "llm_timeout": payload.llm_timeout or (stored.llm_timeout if stored else 45.0) or 45.0,
        "embed_base_url": payload.embed_base_url or (stored.embed_base_url if stored else "") or DEFAULT_BASE_URL,
        "embed_api_key": payload.embed_api_key or (decrypt_secret(stored.embed_api_key) if stored else ""),
        "embed_model": payload.embed_model or (stored.embed_model if stored else "") or "jiaorong-qwen3-embedding-8b",
        "embed_dim": payload.embed_dim or (stored.embed_dim if stored else 1024) or 1024,
    }


async def _verify_candidate(candidate: dict) -> dict:
    """Check both providers and return only safe, displayable failure details."""
    result = {"llm_ok": False, "embed_ok": False, "llm_error": None, "embed_error": None}

    if candidate["llm_api_key"] and candidate["llm_model"]:
        try:
            adapter = OpenAICompatLLMAdapter(
                base_url=candidate["llm_base_url"],
                api_key=candidate["llm_api_key"],
                model=candidate["llm_model"],
                timeout=min(candidate["llm_timeout"], 15.0),
            )
            await adapter.chat(
                [{"role": "user", "content": "ping"}],
                max_tokens=16,
                timeout=min(candidate["llm_timeout"], 15.0),
            )
            result["llm_ok"] = True
        except Exception as exc:  # noqa: BLE001
            result["llm_error"] = f"连接失败（{type(exc).__name__}）"
    else:
        result["llm_error"] = "请填写 LLM 的 API Key 与模型名称"

    if candidate["embed_api_key"] and candidate["embed_model"]:
        try:
            emb = OpenAICompatEmbeddingAdapter(
                base_url=candidate["embed_base_url"],
                api_key=candidate["embed_api_key"],
                model=candidate["embed_model"],
                dim=candidate["embed_dim"],
            )
            vectors = emb.embed(["测试向量化连通性"])
            if vectors and len(vectors[0]) > 0:
                result["embed_ok"] = True
            else:
                result["embed_error"] = "服务未返回有效向量"
        except Exception as exc:  # noqa: BLE001
            result["embed_error"] = f"连接失败（{type(exc).__name__}）"
    else:
        result["embed_error"] = "请填写 Embedding 的 API Key 与模型名称"
    return result


def _apply_candidate(row: ModelConfig, candidate: dict, *, enabled: bool) -> None:
    row.llm_base_url = candidate["llm_base_url"]
    row.llm_api_key = encrypt_secret(candidate["llm_api_key"])
    row.llm_model = candidate["llm_model"]
    row.llm_timeout = candidate["llm_timeout"]
    row.embed_base_url = candidate["embed_base_url"]
    row.embed_api_key = encrypt_secret(candidate["embed_api_key"])
    row.embed_model = candidate["embed_model"]
    row.embed_dim = candidate["embed_dim"]
    row.enabled = enabled


def _activate_runtime(row: ModelConfig) -> None:
    """Call only after the database transaction is committed successfully."""
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


@router.get("/model-config")
async def get_model_config(
    _: object = Depends(require_roles("R4")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(select(ModelConfig).where(ModelConfig.id == SINGLETON_ID))
    ).scalar_one_or_none()
    return ok(_mask_row(row) if row else _default_payload())


@router.put("/model-config")
async def update_model_config(
    payload: ModelConfigIn,
    _: object = Depends(require_roles("R4")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(select(ModelConfig).where(ModelConfig.id == SINGLETON_ID))
    ).scalar_one_or_none()
    candidate = _resolve_candidate(payload, row)

    # Explicit offline mode is an intentional mode switch. Keep the last known
    # real configuration for a later re-enable, but make the runtime mock-only.
    if not payload.enabled:
        if row is None:
            row = ModelConfig(id=SINGLETON_ID)
            db.add(row)
        _apply_candidate(row, candidate, enabled=False)
        await db.commit()
        _activate_runtime(row)
        return ok(_mask_row(row), message="已切换至本地 mock 模型")

    # P0: neither the database row nor the runtime is changed before BOTH
    # candidate providers pass their real connectivity checks.
    result = await _verify_candidate(candidate)
    if not (result["llm_ok"] and result["embed_ok"]):
        raise BadRequestError("模型连接校验失败，未保存也未启用新配置", data=result)

    if row is None:
        row = ModelConfig(id=SINGLETON_ID)
        db.add(row)
    _apply_candidate(row, candidate, enabled=True)
    await db.commit()
    _activate_runtime(row)
    return ok(_mask_row(row), message="模型连接校验通过，已保存并启用")


@router.post("/model-config/test")
async def test_model_config(
    payload: ModelConfigIn,
    _: object = Depends(require_roles("R4")),
    db: AsyncSession = Depends(get_db),
):
    """Test a candidate without persisting or enabling it."""
    row = (
        await db.execute(select(ModelConfig).where(ModelConfig.id == SINGLETON_ID))
    ).scalar_one_or_none()
    return ok(await _verify_candidate(_resolve_candidate(payload, row)))
