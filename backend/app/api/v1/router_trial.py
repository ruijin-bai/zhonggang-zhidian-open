"""Real-trial evidence endpoints with strict role and provenance boundaries."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_roles
from app.core.exceptions import ok
from app.db.models.trial import TrialBenchmarkRecord, TrialUsageEvent
from app.db.session import get_db
from app.schemas.trial import TrialBenchmarkCreate, TrialEventCreate
from app.services.audit import record_audit
from app.services.trial import build_trial_summary

router = APIRouter(prefix="/trial", tags=["trial"])


@router.post("/events", response_model=None)
async def create_event(body: TrialEventCreate, user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    event = TrialUsageEvent(user_id=user.user_id, role=user.role, **body.model_dump())
    db.add(event)
    await db.commit()
    return ok({"event_id": event.event_id})


@router.post("/benchmark", response_model=None)
async def create_benchmark(
    body: TrialBenchmarkCreate,
    user=Depends(require_roles("R4")),
    db: AsyncSession = Depends(get_db),
):
    row = TrialBenchmarkRecord(**body.model_dump())
    db.add(row)
    await db.flush()
    await record_audit(
        db, actor_id=user.user_id, action="trial.benchmark.created",
        target_type="trial_benchmark", target_id=row.record_id,
        detail=f"scenario={row.scenario};participant_hash={row.participant_id_hash[:8]}",
    )
    await db.commit()
    return ok({"record_id": row.record_id})


@router.get("/summary", response_model=None)
async def summary(_: object = Depends(require_roles("R2", "R4")), db: AsyncSession = Depends(get_db)):
    return ok(await build_trial_summary(db))


@router.get("/export", response_model=None)
async def export(_: object = Depends(require_roles("R4")), db: AsyncSession = Depends(get_db)):
    rows = list(
        (await db.execute(select(TrialBenchmarkRecord).order_by(TrialBenchmarkRecord.created_at))).scalars()
    )
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow([
        "record_id", "scenario", "participant_id_hash", "manual_duration_seconds",
        "ai_duration_seconds", "manual_success", "ai_success", "manual_source_found",
        "ai_source_found", "notes", "created_at",
    ])
    for row in rows:
        writer.writerow([
            row.record_id, row.scenario, row.participant_id_hash, row.manual_duration_seconds,
            row.ai_duration_seconds, row.manual_success, row.ai_success, row.manual_source_found,
            row.ai_source_found, row.notes or "", row.created_at.isoformat() if row.created_at else "",
        ])
    payload = "\ufeff" + out.getvalue()
    return StreamingResponse(
        iter([payload.encode("utf-8")]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=trial_benchmark.csv"},
    )
