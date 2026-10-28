"""Minimal, transactional publication rules for regulation versions."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.db.enums import ClauseStatus, RegulationStatus
from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile
from app.db.models.relation import Relation
from app.db.models.rule import DecisionRule
from app.db.enums import DecisionRuleStatus
from app.services.governance_state import authority_gaps, source_verification


async def validate_version_submission(
    session: AsyncSession,
    *,
    regulation_code: str,
    version: str,
    replaces_file_id: str | None,
) -> None:
    """Reject ambiguous submissions before storing their source document."""
    # An unknown official number does not group unrelated documents together.
    # A replacement can still be explicitly identified by its stable file ID.
    if not regulation_code:
        if replaces_file_id:
            old = await session.get(RegulationFile, replaces_file_id)
            if old is None or old.regulation_code or old.status != RegulationStatus.CURRENT.value:
                raise BadRequestError("被替代资料不存在、不是现行版本或应保留其已有正式文号")
        return
    duplicate = (
        await session.execute(
            select(RegulationFile.file_id).where(
                RegulationFile.regulation_code == regulation_code,
                RegulationFile.version == version,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise BadRequestError("该制度编码与版本号已存在")

    in_flight = (
        await session.execute(
            select(RegulationFile.file_id).where(
                RegulationFile.regulation_code == regulation_code,
                RegulationFile.status.in_(
                    [RegulationStatus.PROCESSING.value, RegulationStatus.PENDING_REVIEW.value]
                ),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if in_flight is not None:
        raise BadRequestError("该制度存在正在解析或待审核的版本，请处理完成后再提交新版本")

    current = list(
        (
            await session.execute(
                select(RegulationFile).where(
                    RegulationFile.regulation_code == regulation_code,
                    RegulationFile.status == RegulationStatus.CURRENT.value,
                )
            )
        ).scalars()
    )
    if current and not replaces_file_id:
        raise BadRequestError("该制度已有现行版本，请指定被替代版本")
    if replaces_file_id:
        old = await session.get(RegulationFile, replaces_file_id)
        if old is None or old.regulation_code != regulation_code:
            raise BadRequestError("被替代制度不存在或制度编码不一致")
        if old.status != RegulationStatus.CURRENT.value:
            raise BadRequestError("被替代制度不是现行版本")


async def publish_regulation(session: AsyncSession, regulation: RegulationFile) -> None:
    """Publish a parsed regulation and isolate the version it replaces.

    This runs in the ingestion transaction, after clauses and embeddings have
    succeeded.  A failed parse therefore never retires a working current
    version.  Both the old file and its clauses become ineligible for retrieval.
    """
    gaps = authority_gaps(regulation)
    if gaps and source_verification(regulation) != "maintainer":
        labels = {
            "regulation_code": "制度编码",
            "effective_date": "生效日期",
            "owner_org": "责任部门",
            "domain": "制度域",
        }
        raise BadRequestError("发布前必须完成权威元数据核验：" + "、".join(labels[item] for item in gaps))

    if regulation.replaces_file_id:
        old = await session.get(RegulationFile, regulation.replaces_file_id)
        if (
            old is None
            or old.regulation_code != regulation.regulation_code
            or old.status != RegulationStatus.CURRENT.value
        ):
            raise BadRequestError("发布时被替代制度不可用")
        old.status = RegulationStatus.REPLACED.value
        await session.execute(
            update(Clause)
            .where(Clause.file_id == old.file_id, Clause.status == ClauseStatus.CURRENT.value)
            .values(status=ClauseStatus.ISOLATED.value)
        )
        # Rules derived from the replaced version are retained as audit evidence
        # but cannot continue to drive new business conclusions.
        await session.execute(
            update(DecisionRule)
            .where(DecisionRule.file_id == old.file_id, DecisionRule.status == DecisionRuleStatus.CURRENT.value)
            .values(status=DecisionRuleStatus.RETIRED.value)
        )
        existing_relation = (
            await session.execute(
                select(Relation.rel_id).where(
                    Relation.from_id == regulation.file_id,
                    Relation.to_id == old.file_id,
                    Relation.rel_type == "replace",
                )
            )
        ).scalar_one_or_none()
        if existing_relation is None:
            session.add(
                Relation(
                    from_id=regulation.file_id,
                    to_id=old.file_id,
                    rel_type="replace",
                    note="制度版本替代关系（系统生成）",
                    confirmed_by=regulation.reviewed_by,
                )
            )
    elif regulation.regulation_code:
        current = (
            await session.execute(
                select(RegulationFile.file_id).where(
                    RegulationFile.regulation_code == regulation.regulation_code,
                    RegulationFile.status == RegulationStatus.CURRENT.value,
                    RegulationFile.file_id != regulation.file_id,
                )
            )
        ).scalar_one_or_none()
        if current is not None:
            raise BadRequestError("该制度已有现行版本，请指定被替代版本")

    regulation.status = RegulationStatus.CURRENT.value
    regulation.published_at = datetime.now(timezone.utc)
    await session.flush()


async def announce_regulation_publication(session: AsyncSession, regulation: RegulationFile) -> None:
    """Keep employee update notices and historical impact for self-confirmed releases."""
    from app.db.enums import PushStatus
    from app.db.models.permission import Permission
    from app.db.models.push import PushRecord, PushReceipt
    from app.db.models.user import User
    from app.services.impact.analyzer import generate_change_impact
    from app.services.permission.rbac import build_filter

    actor_id = (regulation.source_confirmation or {}).get("actor_id") or regulation.reviewed_by
    old = await session.get(RegulationFile, regulation.replaces_file_id) if regulation.replaces_file_id else None
    await generate_change_impact(session, new_file=regulation, old_file=old, actor_id=actor_id)
    if await session.scalar(select(PushRecord.push_id).where(PushRecord.file_id == regulation.file_id)):
        return
    push = PushRecord(file_id=regulation.file_id, status=PushStatus.SENT.value,
        digest=f"《{regulation.title}》{'已更新' if old else '已可查阅'}（{regulation.version or 'v1'}），请查阅原文及适用范围。",
        created_by=actor_id)
    session.add(push)
    await session.flush()
    permissions = list((await session.scalars(select(Permission))).all())
    users = list((await session.scalars(select(User).where(User.is_active.is_(True)))).all())
    for user in users:
        own = [permission for permission in permissions if permission.role == user.role]
        visible = await session.scalar(select(RegulationFile.file_id).where(
            RegulationFile.file_id == regulation.file_id, build_filter(user, own)))
        if visible:
            session.add(PushReceipt(push_id=push.push_id, user_id=user.user_id))
    await session.flush()
