"""Durable ingestion job recovery tests."""
from __future__ import annotations

from app.adapters.storage.object_store import get_object_store
from app.db.models.ingestion import IngestionJob
from app.db.models.regulation import RegulationFile
from app.services.ingestion.ingest_job import process_ingestion_job, resume_pending_ingestion_jobs


async def test_running_job_is_requeued_and_recovered_from_object_storage(session):
    store = get_object_store()
    object_key = store.put_object(
        "recovery_policy.txt",
        "第一条 恢复测试条款\n恢复后的入库任务应完成。".encode("utf-8"),
        "text/plain",
    )
    regulation = RegulationFile(
        file_id="file_recovery",
        regulation_code="ZG-RECOVERY-001",
        title="恢复测试制度",
        version="v1",
        object_key=object_key,
        status="processing",
    )
    job = IngestionJob(
        job_id="ingest_recovery",
        file_id=regulation.file_id,
        source_filename="recovery_policy.txt",
        status="running",
        attempt_count=1,
    )
    session.add_all([regulation, job])
    await session.commit()

    resumed = await resume_pending_ingestion_jobs(schedule=False)
    await session.refresh(job)
    assert resumed == [job.job_id]
    assert job.status == "pending"

    await process_ingestion_job(job.job_id)
    await session.refresh(job)
    await session.refresh(regulation)
    assert job.status == "succeeded"
    assert job.attempt_count == 2
    assert regulation.status == "pending_review"
    assert regulation.ingest_error is None
