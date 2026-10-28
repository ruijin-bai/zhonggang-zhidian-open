"""Update-push endpoints: notify, center, receipt, recall (T13)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, require_roles
from app.core.exceptions import NotFoundError, ok
from app.db.enums import ReadStatus
from app.db.models.push import PushRecord, PushReceipt
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.push import PushCenterOut, PushNotifyRequest, PushRecordOut, ReceiptBatchUpdate, ReceiptUpdate
from app.services.push.notifier import notify

router = APIRouter(prefix="/push", tags=["push"])


@router.post("/notify", response_model=None)
async def do_notify(
    body: PushNotifyRequest,
    admin: User = Depends(require_roles("R3", "R4")),
    db: AsyncSession = Depends(get_db),
):
    record = await notify(
        db,
        file_id=body.file_id,
        require_review=body.require_review,
        actor_id=admin.user_id,
        target_role=body.target_role,
        scenario_tag=body.scenario_tag,
        old_file_id=body.old_file_id,
    )
    await db.commit()
    return ok({"push_id": record.push_id, "status": record.status})


@router.get("/center", response_model=None)
async def center(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # A normal user can only see notifications with a receipt addressed to
    # them. R3/R4 retain the operational ledger view needed for governance.
    receipts = list((await db.execute(select(PushReceipt).where(PushReceipt.user_id == user.user_id))).scalars().all())
    by_push: dict[str, dict] = {}
    for r in receipts:
        agg = by_push.setdefault(r.push_id, {"read": 0, "unread": 0})
        if r.read_status == ReadStatus.READ.value:
            agg["read"] += 1
        else:
            agg["unread"] += 1

    if user.role in {"R3", "R4"}:
        records_stmt = select(PushRecord).order_by(PushRecord.push_time.desc())
    else:
        records_stmt = (
            select(PushRecord)
            .join(PushReceipt, PushReceipt.push_id == PushRecord.push_id)
            .where(PushReceipt.user_id == user.user_id, PushRecord.status == "sent")
            .order_by(PushRecord.push_time.desc())
        )
    records = list((await db.execute(records_stmt)).scalars().all())
    pushes = []
    total_unread = 0
    for rec in records:
        if user.role in {"R3", "R4"}:
            agg = by_push.get(rec.push_id, {"read": 0, "unread": 0})
        else:
            own = next((r for r in receipts if r.push_id == rec.push_id), None)
            agg = {"read": 1, "unread": 0} if own and own.read_status == ReadStatus.READ.value else {"read": 0, "unread": 1}
        total_unread += agg["unread"]
        pushes.append(
            PushRecordOut(
                push_id=rec.push_id, file_id=rec.file_id, target_role=rec.target_role,
                scenario_tag=rec.scenario_tag, status=rec.status, digest=rec.digest,
                created_by=rec.created_by, read_count=agg["read"], unread_count=agg["unread"],
                push_time=rec.push_time.isoformat() if rec.push_time else None,
            ).model_dump()
        )
    return ok(PushCenterOut(pushes=pushes, total_unread=total_unread).model_dump())


@router.post("/receipts/batch", response_model=None)
async def mark_read_batch(
    body: ReceiptBatchUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(PushReceipt).where(PushReceipt.user_id == user.user_id)
    if body.push_ids is not None:
        stmt = stmt.where(PushReceipt.push_id.in_(body.push_ids))
    receipts = list((await db.execute(stmt)).scalars().all())
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    changed = 0
    target = ReadStatus.READ.value if body.read else ReadStatus.UNREAD.value
    for receipt in receipts:
        if receipt.read_status == target:
            continue
        receipt.read_status = target
        receipt.read_at = now if body.read else None
        changed += 1
    await db.commit()
    return ok({"updated": changed})


@router.post("/receipt/{push_id}", response_model=None)
async def mark_read(
    push_id: str, body: ReceiptUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    receipt = (
        await db.execute(
            select(PushReceipt).where(PushReceipt.push_id == push_id, PushReceipt.user_id == user.user_id)
        )
    ).scalar_one_or_none()
    if receipt is None:
        raise NotFoundError("未找到该推送回执")
    from datetime import datetime, timezone

    receipt.read_status = ReadStatus.READ.value if body.read else ReadStatus.UNREAD.value
    receipt.read_at = datetime.now(timezone.utc) if body.read else None
    await db.flush()
    await db.commit()
    return ok({"push_id": push_id})


@router.post("/{push_id}/recall", response_model=None)
async def recall(push_id: str, _: User = Depends(require_roles("R4")), db: AsyncSession = Depends(get_db)):
    rec = await db.get(PushRecord, push_id)
    if rec is None:
        raise NotFoundError("推送不存在")
    rec.status = "recalled"
    await db.flush()
    await db.commit()
    return ok({"push_id": push_id, "status": "recalled"})
