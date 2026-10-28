"""API authorization tests for relation visibility and evaluation test sets."""
from __future__ import annotations

import httpx

from app.adapters.embedding.factory import get_embedding_adapter
from app.core.security import hash_password
from app.db.models.clause import Clause
from app.db.models.eval import TestCase
from app.db.models.permission import Permission
from app.db.models.relation import Relation
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.main import app
from app.services.auth.auth_service import issue_token


async def _seed_user(session, user_id: str, role: str) -> User:
    user = User(
        user_id=user_id,
        username=user_id,
        hashed_password=hash_password("Zhonggang@123"),
        role=role,
        secret_clearance="internal",
    )
    session.add(user)
    await session.flush()
    return user


async def test_relation_list_and_graph_hide_relations_to_invisible_regulations(session):
    user = await _seed_user(session, "u_relation_reader", "R1")
    session.add(Permission(role="R1", org_scope="/", secret_level="internal", domain="*"))
    visible_a = RegulationFile(file_id="rel_visible_a", title="可见制度甲", org_path="/", secret_level="internal")
    visible_b = RegulationFile(file_id="rel_visible_b", title="可见制度乙", org_path="/", secret_level="internal")
    hidden = RegulationFile(file_id="rel_hidden", title="绝密制度", org_path="/", secret_level="secret")
    session.add_all([visible_a, visible_b, hidden])
    await session.flush()
    session.add_all([
        Relation(rel_id="rel_visible", from_id=visible_a.file_id, to_id=visible_b.file_id, rel_type="subordinate"),
        Relation(rel_id="rel_hidden", from_id=visible_a.file_id, to_id=hidden.file_id, rel_type="conflict", note="绝密制度冲突"),
    ])
    await session.commit()

    headers = {"Authorization": f"Bearer {issue_token(user)}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        relation_list = await client.get("/api/v1/relations", headers=headers)
        graph = await client.get("/api/v1/relations/graph", headers=headers)

    assert relation_list.status_code == 200
    assert [item["rel_id"] for item in relation_list.json()["data"]] == ["rel_visible"]
    assert graph.status_code == 200
    graph_data = graph.json()["data"]
    assert {node["id"] for node in graph_data["nodes"]} == {"rel_visible_a", "rel_visible_b"}
    assert [edge["rel_id"] for edge in graph_data["edges"]] == ["rel_visible"]
    assert "绝密制度" not in str(graph_data)


async def test_eval_testset_read_requires_r3_or_r4(session):
    r1 = await _seed_user(session, "u_eval_r1", "R1")
    r3 = await _seed_user(session, "u_eval_r3", "R3")
    session.add(TestCase(case_id="case_auth", question="测试问题", expected_clause_ids=[]))
    await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        anonymous = await client.get("/api/v1/eval/testset")
        r1_response = await client.get(
            "/api/v1/eval/testset", headers={"Authorization": f"Bearer {issue_token(r1)}"}
        )
        r3_response = await client.get(
            "/api/v1/eval/testset", headers={"Authorization": f"Bearer {issue_token(r3)}"}
        )

    assert anonymous.status_code == 401
    assert r1_response.status_code == 403
    assert r3_response.status_code == 200
    assert r3_response.json()["data"][0]["case_id"] == "case_auth"


async def test_clause_level_secret_is_hidden_from_clause_apis_and_qa(session):
    user = await _seed_user(session, "u_clause_reader", "R1")
    # The user's personal clearance is secret, but their role policy permits internal only.
    user.secret_clearance = "secret"
    session.add(Permission(role="R1", org_scope="/", secret_level="internal", domain="*"))
    file = RegulationFile(
        file_id="file_clause_api", title="项目管理制度", org_path="/", secret_level="internal", status="current"
    )
    session.add(file)
    await session.flush()
    internal_content = "项目审批应按内部流程执行。"
    confidential_content = "机密审批要求仅限授权人员查阅。"
    vectors = get_embedding_adapter().embed([internal_content, confidential_content])
    session.add_all([
        Clause(
            clause_id="clause_api_internal", file_id=file.file_id, clause_no="第一条", content=internal_content,
            secret_level="internal", embedding=vectors[0], status="current",
        ),
        Clause(
            clause_id="clause_api_confidential", file_id=file.file_id, clause_no="第二条", content=confidential_content,
            secret_level="confidential", embedding=vectors[1], status="current",
        ),
    ])
    await session.commit()

    headers = {"Authorization": f"Bearer {issue_token(user)}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        clauses = await client.get("/api/v1/regulations/file_clause_api/clauses", headers=headers)
        preview = await client.get("/api/v1/regulations/file_clause_api/preview", headers=headers)
        canonical_detail = await client.get("/api/v1/clauses/clause_api_confidential", headers=headers)
        legacy_detail = await client.get("/api/v1/regulations/clauses/clause_api_confidential", headers=headers)
        qa_response = await client.post(
            "/api/v1/qa/ask", json={"question": "机密审批要求是什么？", "round": 3}, headers=headers
        )

    assert clauses.status_code == 200
    assert [item["clause_id"] for item in clauses.json()["data"]] == ["clause_api_internal"]
    assert preview.status_code == 200
    assert [item["clause_id"] for item in preview.json()["data"]["clauses"]] == ["clause_api_internal"]
    assert canonical_detail.status_code == 404
    assert legacy_detail.status_code == 404
    assert qa_response.status_code == 200
    assert confidential_content not in qa_response.text
