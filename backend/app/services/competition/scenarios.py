"""Evidence-based validator for the 3-5 featured competition scenarios."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.business_case import BusinessCase
from app.db.models.clause import Clause
from app.db.models.eval import TestCase
from app.db.models.impact import ChangeImpactItem, ChangeImpactRun
from app.db.models.regulation import RegulationFile
from app.db.models.rule import DecisionRule
from app.services.governance_state import is_authority_verified

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "competition_scenarios.json"


def load_scenario_config(path: Path = DEFAULT_CONFIG) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


async def validate_competition_scenarios(db: AsyncSession, config: list[dict] | None = None) -> dict:
    configured = config or load_scenario_config()
    rows: list[dict] = []
    for item in configured:
        scenario = item["scenario"]
        rules = list(
            (
                await db.execute(
                    select(DecisionRule, Clause, RegulationFile)
                    .join(Clause, DecisionRule.clause_id == Clause.clause_id)
                    .join(RegulationFile, DecisionRule.file_id == RegulationFile.file_id)
                    .where(DecisionRule.scenario == scenario)
                )
            ).all()
        )
        current = [(rule, clause, file) for rule, clause, file in rules if rule.status == "current"]
        source_verified = [
            (rule, clause, file) for rule, clause, file in current
            if clause.status == "current" and is_authority_verified(file)
        ]
        reviewed = [row for row in source_verified if row[0].reviewed_by and row[0].reviewed_at]
        if item.get("requires_monetary_boundary"):
            boundary_ready = bool(reviewed) and all(
                rule.currency not in ("", "*")
                and (rule.amount_min_minor is not None or rule.amount_max_minor is not None)
                for rule, _, _ in reviewed
            )
        else:
            boundary_ready = bool(reviewed)
        execution_ready = bool(reviewed) and all(
            bool(rule.org_scope) and bool(rule.approver_path) and bool(rule.required_materials)
            for rule, _, _ in reviewed
        )
        paths = {tuple(rule.approver_path or []) for rule, _, _ in reviewed}
        unexplained_conflict = len(paths) > 1 and any(not (rule.risk_note or "").strip() for rule, _, _ in reviewed)
        cases = list(
            (await db.execute(select(BusinessCase).where(BusinessCase.scenario == scenario))).scalars()
        )
        snapshot_ready = any(
            bool((case.decision_snapshot or {}).get("matched_rule_ids"))
            and bool((case.decision_snapshot or {}).get("evidence"))
            for case in cases
        )
        golden_count = len(
            list(
                (
                    await db.execute(
                        select(TestCase.case_id).where(TestCase.scenario_tag == scenario, TestCase.status == "active")
                    )
                ).scalars()
            )
        )
        old_rule_ids = {rule.rule_id for rule, _, _ in rules if rule.status == "retired"}
        version_items = list(
            (
                await db.execute(
                    select(ChangeImpactItem, ChangeImpactRun)
                    .join(ChangeImpactRun, ChangeImpactItem.impact_id == ChangeImpactRun.impact_id)
                    .where(ChangeImpactItem.object_id.in_(old_rule_ids))
                )
            ).all()
        ) if old_rule_ids else []
        version_ready = any(impact.item_type == "rule_rebuild_required" for impact, _ in version_items)
        checks = {
            "authoritative_source": bool(source_verified),
            "reviewed_current_rules": bool(reviewed),
            "amount_currency_boundary": boundary_ready,
            "approval_path_and_materials": execution_ready,
            "no_unexplained_conflict": not unexplained_conflict,
            "decision_snapshot": snapshot_ready,
            "golden_case_coverage": golden_count > 0,
            "version_impact_cycle": version_ready,
        }
        status = "PASS" if all(checks.values()) else "FAIL"
        rows.append({
            "scenario": scenario,
            "label": item["label"],
            "status": status,
            "checks": checks,
            "counts": {
                "rules_total": len(rules),
                "reviewed_current_rules": len(reviewed),
                "business_cases": len(cases),
                "golden_cases": golden_count,
            },
            "gaps": [key for key, passed in checks.items() if not passed],
        })
    return {
        "scenario_total": len(rows),
        "pass_total": sum(row["status"] == "PASS" for row in rows),
        "all_passed": bool(rows) and all(row["status"] == "PASS" for row in rows),
        "scenarios": rows,
        "disclaimer": "PASS仅表示数据库中存在完整治理证据；场景名称或配置本身不构成业务成熟证明。",
    }
