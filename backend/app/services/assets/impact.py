"""Notify affected requesters without rewriting historical case conclusions."""
from sqlalchemy import select, update

from app.db.models.asset import RetrievalUnit
from app.db.models.business_case import BusinessCase
from app.db.models.push import PushRecord, PushReceipt
from app.db.models.rule import DecisionRule


async def retire_asset_rules_and_notify(session, previous_version_id, new_version_id, actor_id):
    rule_ids = set((await session.execute(select(DecisionRule.rule_id).where(
        DecisionRule.asset_version_id == previous_version_id))).scalars())
    changed = await session.execute(update(DecisionRule).where(
        DecisionRule.asset_version_id == previous_version_id,
        DecisionRule.status.in_(["current", "pending_review"]),
    ).values(status="retired"))
    unit_ids = set((await session.execute(select(RetrievalUnit.unit_id).where(
        RetrievalUnit.version_id == previous_version_id))).scalars())
    affected = 0
    cases = (await session.execute(select(BusinessCase))).scalars()
    for case in cases:
        snapshot = case.decision_snapshot or {}
        evidence = snapshot.get("evidence") or []
        matched = snapshot.get("matched_rule_ids") or []
        uses_old_version = rule_ids.intersection(matched) or any(
            item.get("asset_version_id") == previous_version_id
            or item.get("retrieval_unit_id") in unit_ids
            or item.get("clause_id") in unit_ids
            for item in evidence if isinstance(item, dict)
        )
        if not uses_old_version:
            continue
        affected += 1
        push = PushRecord(file_id=None, scenario_tag=case.scenario, status="sent", created_by=actor_id,
            digest=f"事项 {case.case_no} 的依据资料已有新发布版本。历史结论和证据快照已保留；请在事项办理中核对是否需要重新评估并提交复核。")
        session.add(push)
        await session.flush()
        session.add(PushReceipt(push_id=push.push_id, user_id=case.requester_id, read_status="unread"))
    return {"previous_version_id": previous_version_id, "new_version_id": new_version_id,
        "retired_rule_count": changed.rowcount, "historical_case_count": affected,
        "history_review_required": bool(affected),
        "message": "旧规则已退役；受影响事项的申请人已收到复核提示，历史结论及证据快照保持原样。"}
