"""Deterministic approval-rule and business-case workflow regression tests."""
from __future__ import annotations

from datetime import date

import httpx

from app.core.security import hash_password
from app.db.models.clause import Clause
from app.db.models.permission import Permission
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.db.models.org import OrgUnit
from app.main import app
from app.services.auth.auth_service import issue_token


async def _seed_user(session, user_id: str, role: str, scope: str = "/project-a") -> User:
    user = User(
        user_id=user_id, username=user_id, hashed_password=hash_password("Zhonggang@123"),
        role=role, secret_clearance="secret",
    )
    session.add_all([user, Permission(role=role, org_scope=scope, secret_level="secret", domain="*")])
    await session.flush()
    return user


async def _create_and_approve_rule(client, creator_headers, reviewer_headers, **body):
    created = await client.post("/api/v1/rules", json=body, headers=creator_headers)
    assert created.status_code == 200, created.text
    rule_id = created.json()["data"]["rule_id"]
    reviewed = await client.post(
        f"/api/v1/rules/{rule_id}/review", json={"approved": True, "note": "条款边界已复核"}, headers=reviewer_headers
    )
    assert reviewed.status_code == 200, reviewed.text
    return rule_id


async def test_case_uses_reviewed_integer_boundary_rules_not_llm_guessing(session):
    employee = await _seed_user(session, "case_employee", "R1")
    reviewer = await _seed_user(session, "case_reviewer", "R2", "/")
    curator = await _seed_user(session, "case_curator", "R3", "/")
    session.add(OrgUnit(org_id="org_rule_owner", name="规则责任部门", path="/project-a"))
    await session.flush()
    employee.org_id = "org_rule_owner"
    regulation = RegulationFile(
        file_id="file_case_policy", regulation_code="CHEC-PM-001", title="项目变更管理办法",
        version="v1", status="current", org_path="/project-a", secret_level="internal",
        owner_org="org_rule_owner", effective_date=date(2026, 1, 1), domain="工程",
    )
    clause = Clause(
        clause_id="clause_case_approval", file_id=regulation.file_id, clause_no="第12条",
        content="变更款超过50万美元须区域审核后报总部；10万至50万美元由区域审批；10万美元以下由项目部审批。",
        secret_level="internal", status="current",
    )
    session.add_all([regulation, clause])
    await session.commit()

    employee_headers = {"Authorization": f"Bearer {issue_token(employee)}"}
    reviewer_headers = {"Authorization": f"Bearer {issue_token(reviewer)}"}
    curator_headers = {"Authorization": f"Bearer {issue_token(curator)}"}
    transport = httpx.ASGITransport(app=app)
    common = {
        "scenario": "contract_change", "rule_type": "approval", "file_id": regulation.file_id,
        "clause_id": clause.clause_id, "currency": "USD", "org_scope": "/project-a",
        "required_materials": ["变更申请函", "费用测算表"], "conditions": {},
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        forbidden_rules = await client.get("/api/v1/rules", headers=employee_headers)
        low_rule = await _create_and_approve_rule(
            client, curator_headers, reviewer_headers, **common, rule_key="change-low", priority=10,
            amount_max_minor=10_000_000, max_inclusive=False, approver_path=["项目部审批"],
        )
        mid_rule = await _create_and_approve_rule(
            client, curator_headers, reviewer_headers, **common, rule_key="change-mid", priority=20,
            amount_min_minor=10_000_000, amount_max_minor=50_000_000, min_inclusive=True, max_inclusive=True,
            approver_path=["区域总经理审批"],
        )
        large_rule = await _create_and_approve_rule(
            client, curator_headers, reviewer_headers, **common, rule_key="change-large", priority=30,
            amount_min_minor=50_000_000, min_inclusive=False,
            approver_path=["区域总经理审核", "总部审批"],
        )
        assert low_rule and mid_rule and large_rule

        exact_case = await client.post(
            "/api/v1/cases",
            json={"scenario": "contract_change", "title": "变更款50万美元", "org_path": "/project-a", "amount_minor": 50_000_000, "currency": "USD"},
            headers=employee_headers,
        )
        assert exact_case.status_code == 200, exact_case.text
        exact_evaluated = await client.post(
            f"/api/v1/cases/{exact_case.json()['data']['case_id']}/evaluate", headers=employee_headers
        )
        above_case = await client.post(
            "/api/v1/cases",
            json={"scenario": "contract_change", "title": "变更款50万美元以上", "org_path": "/project-a", "amount_minor": 50_000_001, "currency": "USD"},
            headers=employee_headers,
        )
        above_evaluated = await client.post(
            f"/api/v1/cases/{above_case.json()['data']['case_id']}/evaluate", headers=employee_headers
        )
        incomplete_case = await client.post(
            "/api/v1/cases",
            json={"scenario": "contract_change", "title": "金额未填", "org_path": "/project-a"}, headers=employee_headers
        )
        incomplete_evaluated = await client.post(
            f"/api/v1/cases/{incomplete_case.json()['data']['case_id']}/evaluate", headers=employee_headers
        )

    assert forbidden_rules.status_code == 403
    assert exact_evaluated.status_code == 200, exact_evaluated.text
    exact = exact_evaluated.json()["data"]
    assert exact["status"] == "assessed"
    assert exact["need_human"] is False
    assert exact["decision_snapshot"]["approval_path"] == ["区域总经理审批"]
    assert exact["decision_snapshot"]["matched_rule_ids"] == [mid_rule]
    assert above_evaluated.status_code == 200, above_evaluated.text
    assert above_evaluated.json()["data"]["decision_snapshot"]["approval_path"] == ["区域总经理审核", "总部审批"]
    assert incomplete_evaluated.status_code == 200, incomplete_evaluated.text
    incomplete = incomplete_evaluated.json()["data"]
    assert incomplete["status"] == "review_required"
    assert incomplete["need_human"] is True
    assert "amount_minor" in incomplete["decision_snapshot"]["missing_fields"]
