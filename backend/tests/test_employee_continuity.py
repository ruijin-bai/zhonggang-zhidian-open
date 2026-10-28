"""Personal consultation history and case handoffs must preserve real ownership."""
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.db.models.business_case import BusinessCase
from app.db.models.org import OrgUnit
from app.db.models.permission import Permission
from app.db.models.qa import QACitation, QASession
from app.db.models.user import User
from app.main import app
from app.services.auth.auth_service import issue_token


async def identities(session):
    org = OrgUnit(org_id="continuity_org", name="合成办理组织", path="/continuity")
    owner = User(user_id="continuity_owner", username="continuity_owner", hashed_password="test", role="R1", org_id=org.org_id)
    other = User(user_id="continuity_other", username="continuity_other", hashed_password="test", role="R4", org_id=org.org_id)
    session.add_all([org, owner, other, Permission(role="R1", org_scope="/continuity", secret_level="internal", domain="*"), Permission(role="R4", org_scope="/", secret_level="secret", domain="*")])
    await session.commit()
    return owner, other, {"Authorization": "Bearer " + issue_token(owner)}, {"Authorization": "Bearer " + issue_token(other)}


async def test_history_search_pagination_is_personal_and_literal(session):
    owner, other, headers, other_headers = await identities(session)
    now = datetime.now(timezone.utc)
    session.add_all([
        QASession(session_id="mine_old", user_id=owner.user_id, question="合成变更审批", answer_interpret="已保存解读", created_at=now-timedelta(days=1)),
        QASession(session_id="mine_new", user_id=owner.user_id, question="合成100%_特殊条件", answer_interpret="", created_at=now),
        QASession(session_id="mine_evaluation", user_id=owner.user_id, question="合成评测", is_evaluation=True),
        QASession(session_id="foreign", user_id=other.user_id, question="他人合成隐私", answer_interpret="他人内容"),
        BusinessCase(case_id="linked_owned", case_no="BC-linked-owned", requester_id=owner.user_id, scenario="contract_change", title="合成关联草稿", org_path="/continuity", facts={"source_session": "mine_old"}),
        BusinessCase(case_id="linked_foreign", case_no="BC-linked-foreign", requester_id=other.user_id, scenario="contract_change", title="他人伪造关联", org_path="/continuity", facts={"source_session": "mine_old"}),
    ])
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        first = (await client.get("/api/v1/qa/sessions", params={"limit": 1}, headers=headers)).json()["data"]
        second = (await client.get("/api/v1/qa/sessions", params={"limit": 1, "offset": 1}, headers=headers)).json()["data"]
        assert first["total"] == second["total"] == 2
        assert first["items"][0]["session_id"] == "mine_new" and not first["items"][0]["completed"]
        assert second["items"][0]["session_id"] == "mine_old"
        assert second["items"][0]["linked_case_count"] == 1
        literal = (await client.get("/api/v1/qa/sessions", params={"keyword": "%_"}, headers=headers)).json()["data"]
        assert literal["total"] == 1 and literal["items"][0]["session_id"] == "mine_new"
        admin = (await client.get("/api/v1/qa/sessions", headers=other_headers)).json()["data"]
        assert [row["session_id"] for row in admin["items"]] == ["foreign"]
        inaccessible = await client.get("/api/v1/qa/session/mine_old", headers=other_headers)
        assert inaccessible.status_code == 404


async def test_history_restores_original_evidence_and_only_owned_cases(session):
    owner, other, headers, _ = await identities(session)
    session.add_all([
        QASession(session_id="restore", user_id=owner.user_id, question="原问题", answer_interpret="当时回答", need_human=True),
        QACitation(session_id="restore", clause_id="old_clause", file_title="当时制度", clause_no="第一条", excerpt="当时摘录", content_hash="immutable-hash"),
        BusinessCase(case_id="own_returned", case_no="BC-own-returned", requester_id=owner.user_id, scenario="contract_change", title="本人已退回事项", org_path="/continuity", status="returned", facts={"source_session": "restore"}),
        BusinessCase(case_id="other_case", case_no="BC-other", requester_id=other.user_id, scenario="contract_change", title="外人事项", org_path="/continuity", facts={"source_session": "restore"}),
    ])
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        data = (await client.get("/api/v1/qa/session/restore", headers=headers)).json()["data"]
        assert data["question"] == "原问题" and data["answer_interpret"] == "当时回答"
        assert data["completed"] is True and data["created_at"]
        assert data["citations"][0]["excerpt"] == "当时摘录" and data["citations"][0]["content_hash"] == "immutable-hash"
        assert data["related_cases"] == [{"case_id": "own_returned", "case_no": "BC-own-returned", "title": "本人已退回事项", "status": "returned"}]


async def test_case_source_link_cannot_forge_a_foreign_or_evaluation_session(session):
    owner, other, headers, _ = await identities(session)
    session.add_all([
        QASession(session_id="own_source", user_id=owner.user_id, question="服务端真实原问题", answer_interpret="合成已保存回答"),
        QASession(session_id="foreign_source", user_id=other.user_id, question="外人问题"),
        QASession(session_id="evaluation_source", user_id=owner.user_id, question="评测问题", is_evaluation=True),
    ])
    await session.commit()
    body = {"scenario": "contract_change", "title": "合成咨询关联事项", "facts": {"source_session": "own_source", "source_question": "客户端伪造原问题", "description": "待人工核对"}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/v1/cases", headers=headers, json=body)
        assert created.status_code == 200, created.text
        case = created.json()["data"]
        assert case["facts"]["source_question"] == "服务端真实原问题"
        for source in ("foreign_source", "evaluation_source", "not-real"):
            invalid = {**body, "facts": {"source_session": source}}
            assert (await client.post("/api/v1/cases", headers=headers, json=invalid)).status_code == 404
            assert (await client.put("/api/v1/cases/"+case["case_id"], headers=headers, json=invalid)).status_code == 404
        actual = (await client.get("/api/v1/cases/"+case["case_id"], headers=headers)).json()["data"]
        assert actual["facts"]["source_session"] == "own_source" and actual["status"] == "draft"
        assert len(list((await session.execute(select(BusinessCase))).scalars())) == 1
