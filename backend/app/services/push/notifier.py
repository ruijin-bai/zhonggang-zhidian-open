"""Push notifier: create push records + read receipts, with review gating (T13)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import PushStatus, ReadStatus
from app.db.models.push import PushReceipt, PushRecord
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.services.push.digest import generate_digest
from app.services.push.impact import identify_impact
from app.utils.metrics import PUSH_TOTAL


async def notify(
    session: AsyncSession,
    *,
    file_id: str,
    require_review: bool,
    actor_id: str | None,
    target_role: str | None = None,
    scenario_tag: str | None = None,
    old_file_id: str | None = None,
) -> PushRecord:
    digest = await generate_digest(session, file_id, old_file_id)
    # 影响识别：自动补充受影响范围，使智能推送可见（接入此前未调用的 identify_impact）
    try:
        impact = await identify_impact(session, file_id)
        parts = []
        if impact.get("scenario_tags"):
            parts.append("影响业务场景：" + "、".join(impact["scenario_tags"]))
        if impact.get("roles"):
            parts.append("影响角色：" + "、".join(impact["roles"]))
        if impact.get("related_files"):
            parts.append(f"关联制度文件 {len(impact['related_files'])} 份")
        if parts:
            digest = digest + "\n【影响识别】" + "；".join(parts) + "。"
    except Exception:
        # 影响识别为增强能力，异常不应阻断推送主流程
        pass
    status = PushStatus.PENDING_REVIEW.value if require_review else PushStatus.SENT.value
    record = PushRecord(
        file_id=file_id,
        target_role=target_role,
        scenario_tag=scenario_tag,
        status=status,
        digest=digest,
        created_by=actor_id,
    )
    session.add(record)
    await session.flush()

    if status == PushStatus.SENT.value:
        users = await _target_users(session, target_role, scenario_tag)
        for u in users:
            session.add(
                PushReceipt(push_id=record.push_id, user_id=u.user_id, read_status=ReadStatus.UNREAD.value)
            )
        PUSH_TOTAL.labels(status="sent").inc()
    else:
        PUSH_TOTAL.labels(status="pending_review").inc()

    # Mark the previous version as replaced.
    old = await session.get(RegulationFile, file_id)
    if old is not None and old.status == "current" and old_file_id:
        pass  # version ledger handled by ingestion caller
    await session.flush()
    return record


async def _target_users(
    session: AsyncSession, target_role: str | None, scenario_tag: str | None
) -> list[User]:
    stmt = select(User).where(User.is_active.is_(True))
    if target_role:
        stmt = stmt.where(User.role == target_role)
    if scenario_tag:
        from app.db.models.push import PushSubscription

        subscribed_ids = select(PushSubscription.user_id).where(PushSubscription.scenario_tag == scenario_tag)
        stmt = stmt.where(User.user_id.in_(subscribed_ids))
    return list((await session.execute(stmt)).scalars().all())
