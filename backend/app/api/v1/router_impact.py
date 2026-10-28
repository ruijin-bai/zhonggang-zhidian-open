"""Review and close the operational impacts of an approved regulation change."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_user_context, require_roles
from app.core.exceptions import BadRequestError, NotFoundError, ok
from app.db.models.impact import ChangeImpactItem, ChangeImpactRun
from app.db.models.regulation import RegulationFile
from app.db.session import get_db
from app.schemas.impact import ChangeImpactItemOut, ChangeImpactOut, ImpactConfirmRequest, ImpactResolveRequest
from app.services.audit import record_audit
from app.services.permission.rbac import build_filter

router = APIRouter(prefix="/impacts", tags=["impacts"])


def _item_out(item: ChangeImpactItem) -> dict:
    return ChangeImpactItemOut(
        item_id=item.item_id, item_type=item.item_type, object_type=item.object_type, object_id=item.object_id,
        severity=item.severity, status=item.status, old_snapshot=item.old_snapshot or {}, new_snapshot=item.new_snapshot or {},
        resolution=item.resolution, resolved_by=item.resolved_by, resolved_at=item.resolved_at.isoformat() if item.resolved_at else None,
    ).model_dump()


async def _run_out(db: AsyncSession, run: ChangeImpactRun, include_items: bool = False) -> dict:
    items: list[dict] = []
    if include_items:
        rows = list((await db.execute(select(ChangeImpactItem).where(ChangeImpactItem.impact_id == run.impact_id).order_by(ChangeImpactItem.created_at))).scalars())
        items = [_item_out(item) for item in rows]
    unresolved_high = (
        await db.execute(
            select(ChangeImpactItem.item_id).where(
                ChangeImpactItem.impact_id == run.impact_id,
                ChangeImpactItem.severity == "high",
                ChangeImpactItem.status != "resolved",
            )
        )
    ).all()
    summary = dict(run.summary or {})
    summary["high_risk_open"] = len(unresolved_high)
    new_file = await db.get(RegulationFile, run.new_file_id)
    old_file = await db.get(RegulationFile, run.old_file_id) if run.old_file_id else None
    return ChangeImpactOut(
        impact_id=run.impact_id, new_file_id=run.new_file_id, old_file_id=run.old_file_id, status=run.status,
        new_file_title=new_file.title if new_file else run.new_file_id, new_file_version=new_file.version if new_file else "",
        old_file_title=old_file.title if old_file else None, old_file_version=old_file.version if old_file else None,
        summary=summary, generated_by=run.generated_by, confirmed_by=run.confirmed_by,
        confirmed_at=run.confirmed_at.isoformat() if run.confirmed_at else None, confirmation_note=run.confirmation_note,
        items=items,
    ).model_dump()


async def _accessible_run(db: AsyncSession, impact_id: str, user, perms) -> ChangeImpactRun | None:
    return (
        await db.execute(
            select(ChangeImpactRun)
            .join(RegulationFile, ChangeImpactRun.new_file_id == RegulationFile.file_id)
            .where(ChangeImpactRun.impact_id == impact_id, build_filter(user, perms))
        )
    ).scalar_one_or_none()


@router.get("", response_model=None)
async def list_impacts(
    status: str | None = None,
    _: object = Depends(require_roles("R2", "R3", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, perms = ctx
    stmt = (
        select(ChangeImpactRun)
        .join(RegulationFile, ChangeImpactRun.new_file_id == RegulationFile.file_id)
        .where(build_filter(user, perms))
        .order_by(ChangeImpactRun.created_at.desc())
    )
    if status:
        stmt = stmt.where(ChangeImpactRun.status == status)
    runs = list((await db.execute(stmt)).scalars())
    return ok([await _run_out(db, run) for run in runs])


@router.get("/{impact_id}", response_model=None)
async def impact_detail(
    impact_id: str,
    _: object = Depends(require_roles("R2", "R3", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, perms = ctx
    run = await _accessible_run(db, impact_id, user, perms)
    if run is None:
        raise NotFoundError("影响分析不存在或无权限")
    return ok(await _run_out(db, run, include_items=True))


@router.post("/{impact_id}/items/{item_id}/resolve", response_model=None)
async def resolve_impact_item(
    impact_id: str,
    item_id: str,
    body: ImpactResolveRequest,
    actor=Depends(require_roles("R2", "R3", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, perms = ctx
    run = await _accessible_run(db, impact_id, user, perms)
    if run is None:
        raise NotFoundError("影响分析不存在或无权限")
    item = (
        await db.execute(select(ChangeImpactItem).where(ChangeImpactItem.item_id == item_id, ChangeImpactItem.impact_id == impact_id))
    ).scalar_one_or_none()
    if item is None:
        raise NotFoundError("影响项不存在")
    item.status = "resolved"
    item.resolution = body.resolution.strip()
    item.resolved_by = actor.user_id
    item.resolved_at = datetime.now(timezone.utc)
    await record_audit(
        db, actor_id=actor.user_id, action="impact.item.resolved", target_type="change_impact_item", target_id=item.item_id,
        detail=json.dumps({"impact_id": impact_id, "resolution": item.resolution}, ensure_ascii=False),
    )
    await db.commit()
    return ok(_item_out(item))


@router.post("/{impact_id}/confirm", response_model=None)
async def confirm_impact(
    impact_id: str,
    body: ImpactConfirmRequest,
    actor=Depends(require_roles("R2", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, perms = ctx
    run = await _accessible_run(db, impact_id, user, perms)
    if run is None:
        raise NotFoundError("影响分析不存在或无权限")
    unresolved_high = (
        await db.execute(
            select(ChangeImpactItem.item_id).where(
                ChangeImpactItem.impact_id == impact_id,
                ChangeImpactItem.severity == "high",
                ChangeImpactItem.status != "resolved",
            ).limit(1)
        )
    ).scalar_one_or_none()
    if unresolved_high is not None:
        raise BadRequestError("仍有高风险影响项未处置，不能确认影响分析")
    run.status = "confirmed"
    run.confirmed_by = actor.user_id
    run.confirmed_at = datetime.now(timezone.utc)
    run.confirmation_note = body.note.strip() or None
    await record_audit(db, actor_id=actor.user_id, action="impact.confirmed", target_type="change_impact_run", target_id=run.impact_id)
    await db.commit()
    return ok(await _run_out(db, run, include_items=True))
