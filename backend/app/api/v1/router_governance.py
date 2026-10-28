"""Accountable work queues for closing governance data gaps."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_user_context, require_roles
from app.core.exceptions import BadRequestError, NotFoundError, ok
from app.db.models.governance_task import GovernanceTask
from app.db.models.org import OrgUnit
from app.db.models.regulation import RegulationFile
from app.db.models.rule import DecisionRule
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.governance import GovernanceTaskAction
from app.services.audit import record_audit
from app.services.governance import metadata_missing_fields, sync_governance_tasks
from app.services.permission.rbac import build_filter

router = APIRouter(prefix="/governance", tags=["governance"])


def _payload(task: GovernanceTask, assignee: User | None = None) -> dict:
    return {
        "task_id": task.task_id, "task_key": task.task_key, "task_type": task.task_type,
        "title": task.title, "file_id": task.file_id, "clause_id": task.clause_id,
        "scenario": task.scenario, "status": task.status, "priority": task.priority,
        "missing_fields": task.missing_fields or [], "evidence": task.evidence or {},
        "assignee_id": task.assignee_id, "assignee_name": assignee.username if assignee else None,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "resolution_note": task.resolution_note,
        "resolved_at": task.resolved_at.isoformat() if task.resolved_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


@router.post("/sync", response_model=None)
async def sync_tasks(
    _: object = Depends(require_roles("R3", "R4")),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db),
):
    user, perms = ctx
    result = await sync_governance_tasks(db, user, perms)
    return ok(result)


@router.get("/tasks", response_model=None)
async def list_tasks(
    task_type: str | None = None, status: str | None = None,
    _: object = Depends(require_roles("R2", "R3", "R4")),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db),
):
    user, perms = ctx
    stmt = (
        select(GovernanceTask, User)
        .join(RegulationFile, GovernanceTask.file_id == RegulationFile.file_id)
        .outerjoin(User, GovernanceTask.assignee_id == User.user_id)
        .where(build_filter(user, perms))
        .order_by(GovernanceTask.priority, GovernanceTask.created_at)
    )
    if task_type:
        stmt = stmt.where(GovernanceTask.task_type == task_type)
    if status:
        stmt = stmt.where(GovernanceTask.status == status)
    rows = list((await db.execute(stmt)).all())
    counts: dict[str, int] = {}
    for task, _assignee in rows:
        counts[task.status] = counts.get(task.status, 0) + 1
    return ok({"total": len(rows), "status_counts": counts, "items": [_payload(*row) for row in rows]})


@router.get("/org-units", response_model=None)
async def list_org_units(
    _: object = Depends(require_roles("R3", "R4")), db: AsyncSession = Depends(get_db),
):
    rows = list((await db.execute(select(OrgUnit).order_by(OrgUnit.path))).scalars().all())
    return ok([{"org_id": row.org_id, "name": row.name, "path": row.path} for row in rows])


@router.post("/tasks/{task_id}/action", response_model=None)
async def act_on_task(
    task_id: str, body: GovernanceTaskAction,
    actor: User = Depends(require_roles("R3", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, perms = ctx
    task = (await db.execute(
        select(GovernanceTask)
        .join(RegulationFile, GovernanceTask.file_id == RegulationFile.file_id)
        .where(GovernanceTask.task_id == task_id, build_filter(user, perms))
    )).scalar_one_or_none()
    if task is None:
        raise NotFoundError("治理任务不存在")
    now = datetime.now(timezone.utc)
    if body.action == "claim":
        if task.status in {"resolved", "dismissed"}:
            raise BadRequestError("已关闭任务不能认领")
        if task.assignee_id and task.assignee_id != actor.user_id:
            raise BadRequestError("任务已被其他人员认领")
        task.assignee_id, task.status = actor.user_id, "in_progress"
        task.due_date = body.due_date
    elif body.action == "release":
        if task.assignee_id not in {None, actor.user_id} and actor.role != "R4":
            raise BadRequestError("只能释放本人认领的任务")
        task.assignee_id, task.status, task.due_date = None, "open", None
    elif body.action == "reopen":
        task.status, task.resolved_at, task.resolved_by, task.resolution_note = "open", None, None, None
    elif body.action == "resolve":
        if task.task_type == "regulation_metadata":
            regulation = await db.get(RegulationFile, task.file_id)
            if regulation is None or metadata_missing_fields(regulation):
                raise BadRequestError("元数据仍有缺项，不能标记完成")
        else:
            anchored = (await db.execute(select(DecisionRule.rule_id).where(
                DecisionRule.clause_id == task.clause_id,
                DecisionRule.status.in_(["pending_review", "current"]),
            ))).scalar_one_or_none()
            if anchored is None:
                raise BadRequestError("该条款尚未形成规则草案，不能标记完成")
        task.status, task.resolved_at, task.resolved_by = "resolved", now, actor.user_id
        task.resolution_note = body.note.strip()
    else:  # dismiss
        task.status, task.resolved_at, task.resolved_by = "dismissed", now, actor.user_id
        task.resolution_note = body.note.strip()
    await record_audit(
        db, actor_id=actor.user_id, action=f"governance.task.{body.action}",
        target_type="governance_task", target_id=task.task_id,
        detail=json.dumps({"task_key": task.task_key, "note": body.note.strip()}, ensure_ascii=False),
    )
    await db.commit()
    await db.refresh(task)
    assignee = await db.get(User, task.assignee_id) if task.assignee_id else None
    return ok(_payload(task, assignee))
