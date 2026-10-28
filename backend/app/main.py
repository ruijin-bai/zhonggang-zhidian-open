"""FastAPI application entry point (architecture §5.1, §7).

Mounts all v1 routers, installs the unified error envelope, request tracing,
CORS and the Prometheus /metrics endpoint. On SQLite (local dev) it also creates
tables so the stack boots without running Alembic; production uses PostgreSQL +
Alembic migrations.
"""
from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from app.api.v1 import (
    router_auth,
    router_asset,
    router_case,
    router_clause,
    router_competition,
    router_dashboard,
    router_eval,
    router_impact,
    router_governance,
    router_push,
    router_personal_library,
    router_qa,
    router_relation,
    router_rule,
    router_regulation,
    router_system,
    router_trial,
    router_user,
)
from app.core.config import get_settings
from app.core.exceptions import (
    AppError,
    make_response,
    unhandled_error_handler,
    validation_error_handler,
)
from app.core.logging import configure_logging, get_logger
from app.utils.metrics import metrics_payload
from app.utils.tracer import set_trace_id
from app.db.session import SessionLocal

_SETTINGS = get_settings()
configure_logging(_SETTINGS.LOG_LEVEL)
logger = get_logger("main")

app = FastAPI(title=_SETTINGS.APP_NAME, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_SETTINGS.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def tracing_and_logging(request: Request, call_next):
    trace_id = set_trace_id(request.headers.get(_SETTINGS.TRACE_HEADER))
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001
        logger.error("request_failed", path=request.url.path, error=str(exc))
        return await unhandled_error_handler(request, exc)
    duration = time.perf_counter() - start
    response.headers[_SETTINGS.TRACE_HEADER] = trace_id
    logger.info(
        "request_served",
        path=request.url.path,
        method=request.method,
        status=response.status_code,
        duration_ms=round(duration * 1000, 1),
    )
    return response


app.add_exception_handler(AppError, lambda req, exc: make_response(exc.code, exc.message, exc.data, exc.http_status))
app.add_exception_handler(Exception, unhandled_error_handler)
try:  # pragma: no cover - FastAPI version dependent
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(RequestValidationError, validation_error_handler)
except Exception:  # noqa: BLE001
    pass


API_V1 = _SETTINGS.API_V1_PREFIX
app.include_router(router_auth.router, prefix=API_V1)
app.include_router(router_asset.router, prefix=API_V1)
app.include_router(router_case.router, prefix=API_V1)
app.include_router(router_competition.router, prefix=API_V1)
app.include_router(router_user.router, prefix=API_V1)
app.include_router(router_qa.router, prefix=API_V1)
app.include_router(router_regulation.router, prefix=API_V1)
app.include_router(router_clause.router, prefix=API_V1)
app.include_router(router_relation.router, prefix=API_V1)
app.include_router(router_rule.router, prefix=API_V1)
app.include_router(router_push.router, prefix=API_V1)
app.include_router(router_personal_library.router, prefix=API_V1)
app.include_router(router_eval.router, prefix=API_V1)
app.include_router(router_impact.router, prefix=API_V1)
app.include_router(router_governance.router, prefix=API_V1)
app.include_router(router_dashboard.router, prefix=API_V1)
app.include_router(router_system.router, prefix=API_V1)
app.include_router(router_trial.router, prefix=API_V1)


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(metrics_payload(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/health", include_in_schema=False)
async def health() -> JSONResponse:
    return make_response(0, "ok", {"status": "healthy"})


@app.get("/ready", include_in_schema=False)
async def ready() -> JSONResponse:
    """Readiness probe: verifies that the database accepts a query."""
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        logger.error("readiness_failed", error=str(exc))
        return make_response(50000, "依赖服务不可用", {"status": "not_ready"}, 503)
    return make_response(0, "ok", {"status": "ready"})


@app.on_event("startup")
async def on_startup() -> None:
    if _SETTINGS.is_sqlite:
        # Local dev convenience: create tables so the app boots without Alembic.
        # Production uses PostgreSQL + Alembic migrations (see alembic/).
        from app.db.base import Base
        from app.db import models as _models  # noqa: F401  ensure models are registered
        from app.db.session import engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("sqlite_tables_created", path=_SETTINGS.DATABASE_URL)

    # Runtime model configuration is process-local and must be loaded for both
    # SQLite development and PostgreSQL production deployments.
    from app.services.model_runtime import load_runtime_model_config

    row = await load_runtime_model_config()
    if row is not None:
        logger.info("runtime_model_config_loaded", model=row.llm_model)

    if (
        _SETTINGS.MEMORY_VECTOR_WARMUP_ENABLED
        and (_SETTINGS.is_sqlite or _SETTINGS.VECTOR_BACKEND == "memory")
    ):
        from app.adapters.embedding.factory import get_embedding_adapter
        from app.services.rag.retriever import warm_memory_vector_cache

        expected_dim = int(getattr(get_embedding_adapter(), "dim", 0))
        if expected_dim > 0:
            started = time.perf_counter()
            async with SessionLocal() as session:
                snapshot = await warm_memory_vector_cache(session, expected_dim)
            logger.info(
                "memory_vector_cache_ready",
                count=len(snapshot.clause_ids),
                dimension=expected_dim,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )

    from app.services.ingestion.ingest_job import resume_pending_ingestion_jobs

    resumed = await resume_pending_ingestion_jobs()
    if resumed:
        logger.info("ingestion_jobs_resumed", count=len(resumed))
