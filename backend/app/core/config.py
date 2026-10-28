"""Application configuration loaded from environment / .env via pydantic-settings.

All sensitive values (DATABASE_URL, REDIS_URL, MINIO_*, LLM_*, SECRET_KEY) are
expected to come from the environment or a local ``.env`` file and MUST be
overridden in production through a secret volume.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the 中港智典 backend."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Application ---
    APP_NAME: str = "中港智典"
    API_V1_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"
    TRACE_HEADER: str = "x-trace-id"
    ENVIRONMENT: str = "dev"  # dev | prod

    # --- Database ---
    # Default points to PostgreSQL + pgvector. For local runs without Docker set
    # DATABASE_URL=sqlite+aiosqlite:///./dev.db (in-memory vector fallback is used).
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/zhonggang"
    DB_ECHO: bool = False

    # --- Redis / RQ ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- MinIO (S3 compatible object storage) ---
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "zhonggang"
    MINIO_SECURE: bool = False

    # --- LLM adapter ---
    LLM_PROVIDER: str = "mock"  # mock | openai_compat
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "jiaorong-kimi-k2.6"  # 1T 参数强模型，替代原 flash 快版
    # 快速模型：query 改写 / 自省评估 / 矛盾检测等辅助步骤专用（时延敏感，无需 1T 大模型）
    QA_FAST_MODEL: str = "jiaorong-deepseek-v4-flash"
    # 交融强模型在复杂制度问答中首字可能超过 8 秒。流式接口已经解决客户端
    # 长连接问题，这里应给上游足够的首字/分片等待时间，不能把产品时延目标
    # 误当成供应商请求超时，否则会把正常慢回答错误降级成原文拼接。
    LLM_TIMEOUT: float = 45.0
    LLM_MAX_TOKENS: int = 1500
    LLM_TEMPERATURE: float = 0.2

    # --- Reranker adapter（交融精排模型，优先于 LLM 打分重排；未配置时自动降级） ---
    RERANK_ENABLED: bool = True
    RERANK_MODEL: str = "jiaorong-qwen3-reranker-8b"
    RERANK_TIMEOUT: float = 8.0
    RERANK_BASE_URL: str = "https://c4ai.ccccltd.cn/api/compatible/v1"
    RERANK_API_KEY: str = ""

    # --- Embedding adapter ---
    EMBED_PROVIDER: str = "mock"  # mock | openai_compat
    EMBED_DIM: int = 128
    EMBED_MODEL: str = "text-embedding-3-small"
    EMBED_BASE_URL: str = "https://api.openai.com/v1"
    EMBED_API_KEY: str = ""

    # --- Vector retrieval backend ---
    # pgvector (production) | memory (local fallback using numpy cosine)
    VECTOR_BACKEND: str = "pgvector"
    # SQLite stores vectors as JSON. Build one normalized float32 matrix during
    # startup so the first user query does not pay the full JSON parse cost.
    MEMORY_VECTOR_WARMUP_ENABLED: bool = True

    # Upload ingestion normally runs out-of-band so model/embedding latency does
    # not hold an HTTP connection. It can be disabled for deterministic tests.
    INGEST_ASYNC: bool = True
    # auto: prefer Redis/RQ and fall back to in-process only in development.
    # rq: require durable queue (mandatory in production); inprocess: tests/dev.
    INGEST_QUEUE_BACKEND: str = "auto"

    # --- Structured document parsing ---
    # auto: Docling when its sidecar is configured, otherwise transparent
    # native adapters. docling: fail closed if the sidecar is unavailable.
    DOCUMENT_PARSER_MODE: str = "auto"  # auto | native | docling
    DOCLING_BASE_URL: str = ""
    DOCLING_TIMEOUT_SECONDS: float = 240.0
    PARSE_QUALITY_MIN_SCORE: int = 72

    # --- Auth ---
    SECRET_KEY: str = "change-me-in-production"
    # Runtime model credentials are encrypted at rest. Production must set a
    # separate value; local development falls back to SECRET_KEY so legacy
    # databases can be upgraded without losing their configured provider.
    MODEL_CONFIG_ENCRYPTION_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    # Development-only shared credential used by the role switcher on the
    # login page. Production validation below rejects this mode outright.
    DEMO_LOGIN_ENABLED: bool = False
    DEMO_LOGIN_PASSWORD: str = ""
    # Non-production navigation that only links real business pages. It must be
    # explicitly enabled for rehearsals and carries no seeded outcome data.
    COMPETITION_DEMO_ENABLED: bool = False

    # --- CORS ---
    CORS_ORIGINS: str = "http://localhost:5174,http://localhost:8080"

    # --- RAG tuning ---
    RETRIEVE_TOP_K: int = 5
    RETRIEVE_MIN_SCORE: float = 0.35  # 真实 embedding(4096维)实测：相关≈0.7+，无关≈0.3~0.44
    # 向量粗筛候选池：先 numpy 矩阵运算取余弦 top-N，再对候选池算 BM25+RRF。
    # 避免对全库（3965 条）逐条中文分词/BM25 导致的 4~5s 检索耗时。
    RETRIEVE_PREFILTER: int = 200
    RETRIEVE_LEXICAL_CANDIDATES: int = 200
    FOLLOWUP_MAX_ROUNDS: int = 3

    # --- QA 增强（流式 / 改写 / 重排 / 矛盾检测 / 自省），均可独立关闭，关闭时回退原链路 ---
    QA_STREAM_ENABLED: bool = True
    QA_REWRITE_ENABLED: bool = True        # query 改写：口语 → 规范检索句
    QA_RERANK_ENABLED: bool = True         # LLM 打分重排 top-k 候选
    QA_RERANK_CANDIDATES: int = 20         # 初筛候选池；精排后才收敛到 RETRIEVE_TOP_K
    QA_CONTRADICTION_ENABLED: bool = True  # 检索条款矛盾检测
    QA_SELFCHECK_ENABLED: bool = True      # Agentic 自省闭环：检索充分性评估 + 改写重检索
    QA_REWRITE_TIMEOUT: float = 6.0
    QA_RERANK_TIMEOUT: float = 8.0
    QA_CONTRADICTION_TIMEOUT: float = 6.0
    QA_SELFCHECK_TIMEOUT: float = 8.0
    QA_SELFCHECK_MAX_ROUNDS: int = 2       # 自省重检索最多迭代轮数
    QA_SELFCHECK_TRIGGER_SCORE: float = 0.45  # top 分数低于此值才触发自省评估（0.60 过敏感，真实 reranker 分数下相关条款通常 0.7+）
    QA_DYNAMIC_FOLLOWUP_SCORE: float = 0.50  # 真实 embedding 下低于此值视为检索不充分，触发动态追问

    @model_validator(mode="after")
    def validate_production_security(self):
        if self.ENVIRONMENT.lower() != "prod":
            return self
        errors = []
        if self.is_sqlite:
            errors.append("生产环境禁止使用 SQLite")
        if self.SECRET_KEY == "change-me-in-production" or len(self.SECRET_KEY) < 32:
            errors.append("生产环境必须配置独立且不少于 32 字符的 SECRET_KEY")
        if len(self.MODEL_CONFIG_ENCRYPTION_KEY) < 32:
            errors.append("生产环境必须配置独立且不少于 32 字符的 MODEL_CONFIG_ENCRYPTION_KEY")
        if self.LLM_PROVIDER == "mock" or self.EMBED_PROVIDER == "mock":
            errors.append("生产环境禁止启用 mock 模型适配器")
        if self.DEMO_LOGIN_ENABLED:
            errors.append("生产环境禁止启用开发身份快捷登录")
        if self.INGEST_ASYNC and self.INGEST_QUEUE_BACKEND != "rq":
            errors.append("生产环境异步入库必须使用 Redis/RQ 持久化队列")
        if errors:
            raise ValueError("；".join(errors))
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (single source of truth)."""
    return Settings()


settings = get_settings()
