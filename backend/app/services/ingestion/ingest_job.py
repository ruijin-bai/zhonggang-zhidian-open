"""Durable, recoverable regulation-ingestion job runner."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.adapters.storage.object_store import get_object_store
from app.db.models.ingestion import IngestionJob
from app.db.models.regulation import RegulationFile
from app.db.session import SessionLocal
from app.core.config import get_settings
from app.utils.metrics import INGESTION_FAILED_TOTAL, INGESTION_JOBS_TOTAL, PARSE_BACKEND_TOTAL, PARSE_QUALITY_SCORE

logger = logging.getLogger(__name__)


def _enqueue_rq(job_id: str) -> str:
    from redis import Redis
    from rq import Queue

    settings = get_settings()
    redis = Redis.from_url(settings.REDIS_URL)
    queue = Queue("ingestion", connection=redis)
    job = queue.enqueue(
        "app.services.ingestion.ingest_job.process_ingestion_job_task",
        job_id,
        job_timeout="20m",
        result_ttl=86400,
        failure_ttl=604800,
    )
    return job.id


def schedule_ingestion(job_id: str) -> str:
    """Schedule a persisted job and return the selected execution backend.

    Production requires Redis/RQ. Development ``auto`` mode keeps a safe
    in-process fallback so a missing local Redis does not prevent testing; the
    durable database ledger remains the source of truth in either mode.
    """
    mode = get_settings().INGEST_QUEUE_BACKEND.lower()
    if mode in {"auto", "rq"}:
        try:
            _enqueue_rq(job_id)
            return "rq"
        except Exception:  # noqa: BLE001
            if mode == "rq":
                raise
            logger.warning("ingestion_rq_unavailable_falling_back", extra={"job_id": job_id})
    asyncio.create_task(process_ingestion_job(job_id))
    return "inprocess"


async def resume_pending_ingestion_jobs(schedule: bool = True) -> list[str]:
    """Requeue jobs left pending/running by a process restart.

    A crash cannot lose an upload because source bytes stay in object storage
    and the job stores the source filename. The optional flag keeps this logic
    deterministic in tests without starting background tasks.
    """
    async with SessionLocal() as session:
        jobs = list(
            (
                await session.execute(
                    select(IngestionJob).where(IngestionJob.status.in_(["pending", "running"]))
                )
            ).scalars()
        )
        job_ids = [job.job_id for job in jobs]
        for job in jobs:
            job.status = "pending"
        if jobs:
            await session.commit()
    if schedule:
        for job_id in job_ids:
            schedule_ingestion(job_id)
    return job_ids


async def _mark_failed(job_id: str, reason: str) -> None:
    """Store a safe operational summary without source bytes or credentials."""
    async with SessionLocal() as session:
        job = await session.get(IngestionJob, job_id)
        if job is None:
            return
        INGESTION_FAILED_TOTAL.inc()
        regulation = await session.get(RegulationFile, job.file_id)
        job.status = "failed"
        job.last_error = reason
        job.finished_at = datetime.now(timezone.utc)
        if regulation is not None:
            regulation.status = "failed"
            regulation.ingest_error = reason
        await session.commit()


async def process_ingestion_job(job_id: str) -> None:
    """Execute one persisted ingestion job from its stored original document."""
    from app.services.eval.publish_gate import evaluate_publish_candidate
    from app.services.ingestion.ai_annotate import ai_annotate_clauses
    from app.services.ingestion.ai_summarize import enrich_regulation
    from app.services.ingestion.annotator import append_clauses_to_file
    from app.services.ingestion.embed_job import embed_pending_clauses
    from app.services.ingestion.parser import extract_text
    from app.services.ingestion.structured_parser import parse_document_structured

    async with SessionLocal() as session:
        claim = await session.execute(
            update(IngestionJob)
            .where(IngestionJob.job_id == job_id, IngestionJob.status == "pending")
            .values(
                status="running",
                attempt_count=IngestionJob.attempt_count + 1,
                last_error=None,
                started_at=datetime.now(timezone.utc),
            )
        )
        if claim.rowcount != 1:
            return
        INGESTION_JOBS_TOTAL.inc()
        await session.commit()
        job = await session.get(IngestionJob, job_id)
        if job is None:
            return
        regulation = await session.get(RegulationFile, job.file_id)
        if regulation is None or not regulation.object_key:
            await _mark_failed(job_id, "制度原件不存在，无法恢复入库任务")
            return
        source = get_object_store().get_object(regulation.object_key)
        if source is None:
            await _mark_failed(job_id, "制度原件不可读取，无法恢复入库任务")
            return
        regulation.status = "processing"
        regulation.ingest_error = None
        await session.commit()
        file_id = regulation.file_id
        filename = job.source_filename
        secret_level = regulation.secret_level

    try:
        clauses, parse_report = await parse_document_structured(filename, source)
        PARSE_BACKEND_TOTAL.labels(backend=parse_report.backend or "unknown").inc()
        PARSE_QUALITY_SCORE.observe(parse_report.score)
        if not parse_report.passed:
            reason = "发布评估未通过：解析质量未通过：" + "；".join(
                parse_report.warnings or [f"质量分 {parse_report.score}"]
            )
            await _mark_failed(job_id, reason[:512])
            return

        async with SessionLocal() as session:
            job = await session.get(IngestionJob, job_id)
            regulation = await session.get(RegulationFile, file_id)
            if job is None or regulation is None:
                return
            regulation.parse_backend = parse_report.backend
            regulation.parse_quality_score = parse_report.score
            regulation.parse_quality_report = parse_report.model_dump()
            await append_clauses_to_file(session, file_id, clauses, secret_level=secret_level)
            await embed_pending_clauses(session)
            # 文档摘要 + 元数据抽取（真实 LLM 时优雅降级，失败不阻断入库）
            try:
                full_text = extract_text(filename, source)
                await enrich_regulation(session, regulation, regulation.title, full_text)
            except Exception:  # noqa: BLE001
                logger.warning("enrich_skipped", extra={"file_id": file_id})
            readiness = await evaluate_publish_candidate(session, regulation)
            if not readiness["passed"]:
                INGESTION_FAILED_TOTAL.inc()
                job.status = "failed"
                job.last_error = readiness["reason"]
                job.finished_at = datetime.now(timezone.utc)
                regulation.status = "failed"
                regulation.ingest_error = readiness["reason"]
                await session.commit()
                logger.warning("ingestion_publish_gate_failed", extra={"job_id": job_id, "file_id": file_id})
                return
            from app.services.governance_state import source_verification
            if source_verification(regulation) == "maintainer":
                from app.services.regulation.versioning import publish_regulation, announce_regulation_publication
                await publish_regulation(session, regulation)
                await announce_regulation_publication(session, regulation)
            else:
                regulation.status = "pending_review"
            regulation.ingest_error = None
            job.status = "succeeded"
            job.last_error = None
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()

        asyncio.create_task(ai_annotate_clauses(file_id))
    except Exception:  # noqa: BLE001
        logger.exception("ingestion_job_failed", extra={"job_id": job_id, "file_id": file_id})
        await _mark_failed(job_id, "制度解析或发布处理失败，请检查文件内容后重试")


def process_ingestion_job_task(job_id: str) -> None:
    """RQ worker entry point."""
    async def _run() -> None:
        from app.services.model_runtime import load_runtime_model_config

        await load_runtime_model_config()
        await process_ingestion_job(job_id)

    asyncio.run(_run())
