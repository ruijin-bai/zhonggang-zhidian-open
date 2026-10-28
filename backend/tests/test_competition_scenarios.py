from datetime import date, datetime, timezone

from app.db.models.clause import Clause
from app.db.models.org import OrgUnit
from app.db.models.regulation import RegulationFile
from app.db.models.rule import DecisionRule
from app.services.competition.scenarios import validate_competition_scenarios


async def test_scenario_validator_fails_closed_when_business_evidence_is_incomplete(session):
    result = await validate_competition_scenarios(
        session, [{"scenario": "contract_change", "label": "境外变更", "requires_monetary_boundary": True}]
    )
    row = result["scenarios"][0]
    assert row["status"] == "FAIL"
    assert "authoritative_source" in row["gaps"]
    assert result["all_passed"] is False


async def test_scenario_validator_recognises_governed_rule_evidence_but_not_missing_downstream_cycles(session):
    org = OrgUnit(org_id="org_owner", name="责任部门", org_type="headquarter", path="/hq")
    file = RegulationFile(
        file_id="scenario_file", regulation_code="ZG-C-001", title="境外变更办法", owner_org=org.org_id,
        org_path="/hq", domain="contract_change", effective_date=date(2026, 1, 1), status="current",
    )
    clause = Clause(
        clause_id="scenario_clause", file_id=file.file_id, clause_no="第十二条",
        content="50万美元以上由总部审批。", status="current",
    )
    rule = DecisionRule(
        rule_id="scenario_rule", rule_key="contract_change.usd.500k", scenario="contract_change",
        file_id=file.file_id, clause_id=clause.clause_id, status="current", currency="USD",
        amount_min_minor=50_000_000, min_inclusive=True, org_scope="/hq",
        approver_path=["区域公司", "总部"], required_materials=["变更申请"],
        reviewed_by="biz-reviewer", reviewed_at=datetime.now(timezone.utc),
    )
    session.add_all([org, file, clause, rule])
    await session.commit()
    result = await validate_competition_scenarios(
        session, [{"scenario": "contract_change", "label": "境外变更", "requires_monetary_boundary": True}]
    )
    checks = result["scenarios"][0]["checks"]
    assert checks["authoritative_source"] is True
    assert checks["amount_currency_boundary"] is True
    assert checks["approval_path_and_materials"] is True
    assert checks["decision_snapshot"] is False
    assert result["all_passed"] is False
