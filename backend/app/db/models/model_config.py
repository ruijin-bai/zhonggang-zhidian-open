"""Model configuration (LLM + Embedding) persisted at runtime.

白总偏好：模型名称 / API 地址 / API key 由管理员在前端自助配置，
密钥加密后落地服务端数据库（sqlite 已被 .gitignore 忽略，不进 git），前端脱敏不回显明文。
表为单例行（id 固定 "singleton"），覆盖式更新。
"""
from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ModelConfig(Base):
    """Singleton row holding the active model provider configuration."""

    __tablename__ = "model_config"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="singleton")

    # Whether the runtime uses the configured real provider instead of mock.
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- LLM (大语言模型) ---
    llm_base_url: Mapped[str] = mapped_column(String(512), default="")
    llm_api_key: Mapped[str] = mapped_column(String(512), default="")
    llm_model: Mapped[str] = mapped_column(String(128), default="")
    llm_timeout: Mapped[float] = mapped_column(default=45.0)

    # --- Embedding (向量模型) ---
    embed_base_url: Mapped[str] = mapped_column(String(512), default="")
    embed_api_key: Mapped[str] = mapped_column(String(512), default="")
    embed_model: Mapped[str] = mapped_column(String(128), default="")
    embed_dim: Mapped[int] = mapped_column(Integer, default=1024)
