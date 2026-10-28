"""Deterministic regulation-diff and downstream impact analysis."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.business_case import BusinessCase
from app.db.models.clause import Clause
from app.db.models.impact import ChangeImpactItem, ChangeImpactRun
from app.db.models.regulation import RegulationFile
from app.db.models.rule import DecisionRule


def _clause_snapshot(clause: Clause) -> dict:
    return {"clause_id": clause.clause_id, "clause_no": clause.clause_no, "chapter": clause.chapter or "", "content": clause.content[:1000]}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


async def generate_change_impact(
    session: AsyncSession,
    *,
    new_file: RegulationFile,
    old_file: RegulationFile | None,
    actor_id: str | None,
) -> ChangeImpactRun | None:
    """Build a durable, reviewable diff after an approved version is published."""
    if old_file is None:
        return None
    existing = (
        await session.execute(select(ChangeImpactRun).where(ChangeImpactRun.new_file_id == new_file.file_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    old_clauses = list((await session.execute(select(Clause).where(Clause.file_id == old_file.file_id))).scalars())
    new_clauses = list((await session.execute(select(Clause).where(Clause.file_id == new_file.file_id))).scalars())
    old_by_no = {clause.clause_no: clause for clause in old_clauses if clause.clause_no}
    new_by_no = {clause.clause_no: clause for clause in new_clauses if clause.clause_no}
    items: list[ChangeImpactItem] = []

    for clause_no in sorted(set(old_by_no) & set(new_by_no)):
        old_clause, new_clause = old_by_no[clause_no], new_by_no[clause_no]
        if _normalise(old_clause.content) != _normalise(new_clause.content):
            items.append(ChangeImpactItem(
                item_type="clause_changed", object_type="clause", object_id=new_clause.clause_id, severity="medium",
                old_snapshot=_clause_snapshot(old_clause), new_snapshot=_clause_snapshot(new_clause),
            ))
    for clause_no in sorted(set(old_by_no) - set(new_by_no)):
        old_clause = old_by_no[clause_no]
        items.append(ChangeImpactItem(item_type="clause_removed", object_type="clause", object_id=old_clause.clause_id, severity="high", old_snapshot=_clause_snapshot(old_clause)))
    for clause_no in sorted(set(new_by_no) - set(old_by_no)):
        new_clause = new_by_no[clause_no]
        items.append(ChangeImpactItem(item_type="clause_added", object_type="clause", object_id=new_clause.clause_id, severity="low", new_snapshot=_clause_snapshot(new_clause)))

    old_rules = list((await session.execute(select(DecisionRule).where(DecisionRule.file_id == old_file.file_id))).scalars())
    old_clause_ids = {clause.clause_id for clause in old_clauses}
    old_rule_ids = {rule.rule_id for rule in old_rules}
    for rule in old_rules:
        items.append(ChangeImpactItem(
            item_type="rule_rebuild_required", object_type="decision_rule", object_id=rule.rule_id, severity="high",
            old_snapshot={"rule_key": rule.rule_key, "scenario": rule.scenario, "source_clause_id": rule.clause_id, "status": rule.status},
            new_snapshot={"new_file_id": new_file.file_id, "action": "请基于新版本条款重建并确认规则"},
        ))

    cases = list((await session.execute(select(BusinessCase))).scalars())
    for case in cases:
        evidence = (case.decision_snapshot or {}).get("evidence") or []
        matched = (case.decision_snapshot or {}).get("matched_rule_ids") or []
        if any(item.get("clause_id") in old_clause_ids for item in evidence) or old_rule_ids.intersection(matched):
            items.append(ChangeImpactItem(
                item_type="historical_case_review", object_type="business_case", object_id=case.case_id, severity="high",
                old_snapshot={"case_no": case.case_no, "status": case.status, "decision_summary": case.decision_summary or ""},
                new_snapshot={"action": "请确认该事项的历史结论是否受新版本影响"},
            ))

    summary = {
        "old_file_id": old_file.file_id,
        "new_file_id": new_file.file_id,
        "clause_changed": sum(item.item_type == "clause_changed" for item in items),
        "clause_added": sum(item.item_type == "clause_added" for item in items),
        "clause_removed": sum(item.item_type == "clause_removed" for item in items),
        "rule_rebuild_required": sum(item.item_type == "rule_rebuild_required" for item in items),
        "historical_case_review": sum(item.item_type == "historical_case_review" for item in items),
        "high_risk_open": sum(item.severity == "high" for item in items),
    }
    run = ChangeImpactRun(new_file_id=new_file.file_id, old_file_id=old_file.file_id, summary=summary, generated_by=actor_id)
    session.add(run)
    await session.flush()
    for item in items:
        item.impact_id = run.impact_id
        session.add(item)
    await session.flush()
    return run
