"""Version publication creates a durable, actionable impact chain."""
from __future__ import annotations

from datetime import date

from app.db.models.business_case import BusinessCase
from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile
from app.db.models.rule import DecisionRule
from app.db.models.org import OrgUnit
from app.services.impact.analyzer import generate_change_impact
from app.services.regulation.versioning import publish_regulation


async def test_replacing_a_regulation_retires_rules_and_marks_historical_cases(session):
    session.add(OrgUnit(org_id="org_impact_owner", name="变更责任部门", path="/owner"))
    old = RegulationFile(
        file_id="file_impact_old", regulation_code="CHEC-CHANGE-001", title="变更管理办法", version="v1",
        status="current", org_path="/", secret_level="internal",
    )
    new = RegulationFile(
        file_id="file_impact_new", regulation_code="CHEC-CHANGE-001", title="变更管理办法", version="v2",
        status="pending_review", replaces_file_id=old.file_id, org_path="/", secret_level="internal",
        owner_org="org_impact_owner", effective_date=date(2026, 1, 1), domain="工程",
    )
    old_clause = Clause(
        clause_id="clause_impact_old", file_id=old.file_id, clause_no="第12条", content="旧版变更款由区域审批。",
        secret_level="internal", status="current",
    )
    new_clause = Clause(
        clause_id="clause_impact_new", file_id=new.file_id, clause_no="第12条", content="新版变更款超过阈值须总部审批。",
        secret_level="internal", status="current",
    )
    old_rule = DecisionRule(
        rule_id="rule_impact_old", rule_key="contract-change", scenario="contract_change", file_id=old.file_id,
        clause_id=old_clause.clause_id, status="current", currency="USD", approver_path=["区域审批"], required_materials=[],
    )
    historical_case = BusinessCase(
        case_id="case_impact_history", case_no="BC-IMPACT-001", requester_id="user_impact", scenario="contract_change",
        title="已办理的变更事项", org_path="/", status="assessed", need_human=False,
        decision_snapshot={"matched_rule_ids": [old_rule.rule_id], "evidence": [{"clause_id": old_clause.clause_id}]},
    )
    session.add_all([old, new, old_clause, new_clause, old_rule, historical_case])
    await session.commit()

    await publish_regulation(session, new)
    run = await generate_change_impact(session, new_file=new, old_file=old, actor_id=None)
    await session.commit()
    await session.refresh(old_rule)

    assert run is not None
    assert old_rule.status == "retired"
    assert run.summary["clause_changed"] == 1
    assert run.summary["rule_rebuild_required"] == 1
    assert run.summary["historical_case_review"] == 1
