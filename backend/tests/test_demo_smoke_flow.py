"""Demo critical-path smoke test.

Runs entirely in pytest's isolated SQLite database with mock embedding/LLM
adapters. It protects the competition demonstration path at the HTTP boundary:
R1 login -> visible regulations -> clarification -> cited answer -> RBAC denial.
"""
from __future__ import annotations

import httpx

from app.adapters.embedding.factory import get_embedding_adapter
from app.core.security import hash_password
from app.db.models.clause import Clause
from app.db.models.permission import Permission
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.main import app


async def _seed_demo_data(session) -> tuple[Clause, Clause]:
    employee = User(
        user_id="demo_r1",
        username="demo_employee",
        hashed_password=hash_password("Zhonggang@123"),
        role="R1",
        secret_clearance="internal",
        is_active=True,
    )
    permission = Permission(
        perm_id="perm_demo_r1",
        role="R1",
        org_scope="/hq/region1/overseas1",
        secret_level="internal",
        domain="*",
    )
    visible_file = RegulationFile(
        file_id="file_demo_visible",
        title="境外项目管理办法",
        source="演示制度库",
        version="v1",
        org_path="/hq/region1/overseas1",
        secret_level="internal",
        domain="境外项目",
        status="current",
    )
    confidential_file = RegulationFile(
        file_id="file_demo_confidential",
        title="内部审计工作规定",
        source="演示制度库",
        version="v1",
        org_path="/hq/region1/overseas1",
        secret_level="confidential",
        domain="*",
        status="current",
    )
    session.add_all([employee, permission, visible_file, confidential_file])
    await session.flush()

    visible_text = "境外项目变更款审批：单笔变更款超过50万美元的，须报区域总经理审核后报总部审批。"
    confidential_text = "内部审计组有权调阅全部境外项目财务资料。"
    vectors = get_embedding_adapter().embed([visible_text, confidential_text])
    visible_clause = Clause(
        clause_id="clause_demo_visible",
        file_id=visible_file.file_id,
        clause_no="第12条",
        content=visible_text,
        secret_level="internal",
        scenario_tags=["变更款审批"],
        embedding=vectors[0],
        status="current",
    )
    confidential_clause = Clause(
        clause_id="clause_demo_confidential",
        file_id=confidential_file.file_id,
        clause_no="第4条",
        content=confidential_text,
        secret_level="confidential",
        scenario_tags=["审计"],
        embedding=vectors[1],
        status="current",
    )
    session.add_all([visible_clause, confidential_clause])
    await session.commit()
    return visible_clause, confidential_clause


async def test_r1_demo_qa_flow_and_confidential_clause_denial(session) -> None:
    """The main demo chain must remain runnable without external services."""
    visible_clause, confidential_clause = await _seed_demo_data(session)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"username": "demo_employee", "password": "Zhonggang@123"},
        )
        assert login.status_code == 200, login.text
        assert login.json()["data"]["user"]["role"] == "R1"
        headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

        regulations = await client.get("/api/v1/regulations", headers=headers)
        assert regulations.status_code == 200, regulations.text
        titles = {item["title"] for item in regulations.json()["data"]}
        assert "境外项目管理办法" in titles
        assert "内部审计工作规定" not in titles

        followup = await client.post(
            "/api/v1/qa/ask",
            json={"question": "境外项目变更款由谁审批？", "round": 1},
            headers=headers,
        )
        assert followup.status_code == 200, followup.text
        followup_data = followup.json()["data"]
        assert followup_data["follow_up"] is not None, followup.text
        assert "amount" in followup_data["follow_up"]["missing"]

        answer = await client.post(
            "/api/v1/qa/ask",
            json={
                "question": "境外项目变更款由谁审批？",
                "session_id": followup_data["session_id"],
                "round": 2,
                "slots": {"amount": ">50万", "domestic": "境外", "level": "总部"},
            },
            headers=headers,
        )
        assert answer.status_code == 200, answer.text
        answer_data = answer.json()["data"]
        assert answer_data["follow_up"] is None
        assert answer_data["degraded"] is False
        assert "总部审批" in answer_data["answer_interpret"]
        assert any(item["clause_id"] == visible_clause.clause_id for item in answer_data["citations"])

        denied = await client.get(f"/api/v1/clauses/{confidential_clause.clause_id}", headers=headers)
        assert denied.status_code == 404, denied.text
        assert denied.json()["code"] == 40401
