"""Regression coverage for the product-hardening endpoints."""
from __future__ import annotations

from datetime import date

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import hash_password
from app.db.models.business_case import BusinessCase
from app.db.models.clause import Clause
from app.db.models.org import OrgUnit
from app.db.models.permission import Permission
from app.db.models.push import PushReceipt, PushRecord
from app.db.models.qa import QACitation, QASession
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.main import app
from app.services.auth.auth_service import issue_token


def test_production_configuration_rejects_demo_security_defaults():
    with pytest.raises(ValidationError, match="生产环境"):
        Settings(
            ENVIRONMENT="prod", DATABASE_URL="sqlite+aiosqlite:///./unsafe.db",
            SECRET_KEY="change-me-in-production", MODEL_CONFIG_ENCRYPTION_KEY="",
            LLM_PROVIDER="mock", EMBED_PROVIDER="mock",
        )


async def _admin(session) -> tuple[User, dict[str, str]]:
    user = User(
        user_id="hardening_admin", username="hardening_admin",
        hashed_password=hash_password("StrongPassword!123"), role="R4",
        secret_clearance="secret",
    )
    session.add_all([
        user,
        Permission(role="R4", org_scope="/", secret_level="secret", domain="*"),
    ])
    await session.flush()
    return user, {"Authorization": f"Bearer {issue_token(user)}"}


async def test_workbench_and_batch_receipts_are_user_scoped(session):
    user, headers = await _admin(session)
    file = RegulationFile(
        file_id="file_workbench", regulation_code="CHEC-WB-001", title="工作台制度",
        status="current", effective_date=date(2026, 1, 1), secret_level="internal",
    )
    push = PushRecord(push_id="push_workbench", file_id=file.file_id, status="sent", digest="制度已更新")
    session.add_all([
        file,
        BusinessCase(
            case_id="case_workbench", case_no="CASE-WB-001", requester_id=user.user_id,
            scenario="payment", title="付款申请", org_path="/", status="draft",
        ),
        push,
        PushReceipt(receipt_id="rcpt_workbench", push_id=push.push_id, user_id=user.user_id),
    ])
    await session.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        before = await client.get("/api/v1/dashboard/workbench", headers=headers)
        updated = await client.post("/api/v1/push/receipts/batch", json={"read": True}, headers=headers)
        after = await client.get("/api/v1/dashboard/workbench", headers=headers)

    assert before.status_code == 200, before.text
    assert before.json()["data"]["my_case_open"] == 1
    assert before.json()["data"]["unread_pushes"] == 1
    assert updated.json()["data"]["updated"] == 1
    assert after.json()["data"]["unread_pushes"] == 0


async def test_metadata_gaps_are_explicit_and_auditable(session):
    _user, headers = await _admin(session)
    session.add_all([
        OrgUnit(org_id="org_metadata", name="制度管理部", path="/org_metadata"),
        RegulationFile(
            file_id="file_metadata_gap", regulation_code="待补充制度", title="待补充制度",
            status="current", secret_level="internal", domain="*",
        ),
    ])
    await session.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        gaps = await client.get("/api/v1/regulations/governance/gaps", headers=headers)
        updated = await client.post(
            "/api/v1/regulations/file_metadata_gap/metadata",
            json={
                "regulation_code": "CHEC-GOV-001", "effective_date": "2026-08-01",
                "owner_org": "org_metadata", "domain": "compliance",
                "evidence_note": "制度正式发文页及责任部门确认记录",
            },
            headers=headers,
        )
        closed = await client.get("/api/v1/regulations/governance/gaps", headers=headers)

    assert gaps.status_code == 200, gaps.text
    gap = next(item for item in gaps.json()["data"]["items"] if item["file_id"] == "file_metadata_gap")
    assert set(gap["missing_fields"]) == {"制度编码", "生效日期", "责任部门", "制度域"}
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["regulation_code"] == "CHEC-GOV-001"
    assert all(item["file_id"] != "file_metadata_gap" for item in closed.json()["data"]["items"])


async def test_rule_coverage_pool_returns_source_evidence_only(session):
    _user, headers = await _admin(session)
    file = RegulationFile(
        file_id="file_coverage", regulation_code="CHEC-SAFE-001", title="安全生产管理办法",
        status="current", effective_date=date(2026, 1, 1), secret_level="internal",
    )
    clause = Clause(
        clause_id="clause_coverage", file_id=file.file_id, clause_no="第十二条",
        content="项目发生安全事故时，应启动应急预案并报告安全生产部。",
        secret_level="internal", status="current", scenario_tags=["安全", "应急"],
    )
    session.add_all([file, clause])
    await session.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/rules/coverage", headers=headers)

    assert response.status_code == 200, response.text
    item = next(item for item in response.json()["data"]["items"] if item["clause_id"] == clause.clause_id)
    assert item["scenario"] == "safety"
    assert item["file_title"] == "安全生产管理办法"
    assert item["matched_keywords"]


async def test_governance_tasks_persist_evidence_assignment_and_completion_gate(session):
    _user, headers = await _admin(session)
    file = RegulationFile(
        file_id="file_governance_task", regulation_code="", title="安全费用审批管理办法",
        status="current", secret_level="internal", domain="*",
    )
    date_clause = Clause(
        clause_id="clause_governance_date", file_id=file.file_id, clause_no="第二十条",
        content="本办法自2026年8月1日起施行。", secret_level="internal", status="current",
    )
    rule_clause = Clause(
        clause_id="clause_governance_rule", file_id=file.file_id, clause_no="第十二条",
        content="人民币100万元以上的安全费用申请应提交申请表并报区域公司审批。",
        secret_level="internal", status="current", scenario_tags=["安全", "费用"],
    )
    session.add_all([file, date_clause, rule_clause])
    await session.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        synced = await client.post("/api/v1/governance/sync", headers=headers)
        metadata = await client.get(
            "/api/v1/governance/tasks?task_type=regulation_metadata", headers=headers
        )
        rules = await client.get(
            "/api/v1/governance/tasks?task_type=rule_candidate", headers=headers
        )
        rule_task = next(row for row in rules.json()["data"]["items"] if row["clause_id"] == rule_clause.clause_id)
        claimed = await client.post(
            f"/api/v1/governance/tasks/{rule_task['task_id']}/action",
            json={"action": "claim"}, headers=headers,
        )
        blocked = await client.post(
            f"/api/v1/governance/tasks/{rule_task['task_id']}/action",
            json={"action": "resolve", "note": "已核对"}, headers=headers,
        )

    assert synced.status_code == 200, synced.text
    metadata_task = next(row for row in metadata.json()["data"]["items"] if row["file_id"] == file.file_id)
    assert metadata_task["evidence"]["suggestions"]["effective_date"]["value"] == "2026-08-01"
    assert metadata_task["evidence"]["suggestions"]["domain"]["value"] == "安全"
    assert rule_task["evidence"]["signals"]["amount_mentions"]
    assert rule_task["evidence"]["signals"]["approval_mentions"]
    assert claimed.json()["data"]["status"] == "in_progress"
    assert blocked.status_code == 400


async def test_quality_dashboard_excludes_evaluation_traffic(session):
    user, headers = await _admin(session)
    live = QASession(
        session_id="qa_live", user_id=user.user_id, question="真实问题",
        answer_interpret="真实回答", confidence=0.8, degraded=False,
        is_evaluation=False, need_human=False,
    )
    replay = QASession(
        session_id="qa_replay", user_id=user.user_id, question="回归问题",
        answer_interpret="评测回答", confidence=0.0, degraded=True,
        is_evaluation=True, need_human=True,
    )
    session.add_all([
        live,
        replay,
        QACitation(
            session_id=live.session_id, clause_id="clause_live", file_title="真实制度",
            clause_no="第一条", excerpt="真实依据", consistent=True,
        ),
        QACitation(
            session_id=replay.session_id, clause_id="clause_replay", file_title="评测制度",
            clause_no="第二条", excerpt="评测依据", consistent=True,
        ),
    ])
    await session.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/dashboard/quality", headers=headers)

    data = response.json()["data"]
    assert data["qa_total"] == 1
    assert data["realtime_citation_rate"] == 1.0
    assert data["degraded_rate"] == 0.0
