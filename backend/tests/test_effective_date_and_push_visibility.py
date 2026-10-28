"""Live conclusions and notifications respect effective dates and recipients."""
from __future__ import annotations

from datetime import date, timedelta

import httpx

from app.adapters.embedding.factory import get_embedding_adapter
from app.core.security import hash_password
from app.db.models.clause import Clause
from app.db.models.permission import Permission
from app.db.models.push import PushReceipt, PushRecord
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.main import app
from app.services.auth.auth_service import issue_token
from app.services.rag.retriever import RetrieverService


async def _user(session, user_id: str, role: str = "R1") -> User:
    user = User(user_id=user_id, username=user_id, hashed_password=hash_password("Zhonggang@123"), role=role, secret_clearance="secret")
    session.add_all([user, Permission(role=role, org_scope="/", secret_level="secret", domain="*")])
    await session.flush()
    return user


async def test_retriever_excludes_not_yet_effective_and_expired_regulations(session):
    user = await _user(session, "u_effective")
    text = "项目变更审批规则"
    vector = get_embedding_adapter().embed([text])[0]
    current = RegulationFile(file_id="file_effective_now", title="现行制度", org_path="/", status="current", effective_date=date.today())
    future = RegulationFile(file_id="file_effective_future", title="待生效制度", org_path="/", status="current", effective_date=date.today() + timedelta(days=1))
    expired = RegulationFile(file_id="file_effective_expired", title="过期制度", org_path="/", status="current", expiry_date=date.today() - timedelta(days=1))
    session.add_all([current, future, expired])
    await session.flush()
    for file in (current, future, expired):
        session.add(Clause(file_id=file.file_id, clause_no="第1条", content=text, secret_level="internal", status="current", embedding=vector))
    await session.commit()

    perms = [Permission(role="R1", org_scope="/", secret_level="secret", domain="*")]
    results = await RetrieverService().retrieve(session, user, perms, text, top_k=10, min_score=0.0)
    assert [item.file.file_id for item in results] == [current.file_id]


async def test_push_center_returns_only_the_current_users_received_notifications(session):
    employee = await _user(session, "u_push_employee")
    other = await _user(session, "u_push_other")
    admin = await _user(session, "u_push_admin", "R3")
    own_push = PushRecord(push_id="push_owned", status="sent", digest="本人可见通知")
    other_push = PushRecord(push_id="push_other", status="sent", digest="不应泄露通知")
    pending_push = PushRecord(push_id="push_pending", status="pending_review", digest="待审核通知")
    session.add_all([own_push, other_push, pending_push])
    await session.flush()
    session.add_all([PushReceipt(push_id=own_push.push_id, user_id=employee.user_id), PushReceipt(push_id=other_push.push_id, user_id=other.user_id)])
    await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        employee_center = await client.get("/api/v1/push/center", headers={"Authorization": f"Bearer {issue_token(employee)}"})
        admin_center = await client.get("/api/v1/push/center", headers={"Authorization": f"Bearer {issue_token(admin)}"})

    assert employee_center.status_code == 200
    assert [row["push_id"] for row in employee_center.json()["data"]["pushes"]] == ["push_owned"]
    assert admin_center.status_code == 200
    assert {row["push_id"] for row in admin_center.json()["data"]["pushes"]} == {"push_owned", "push_other", "push_pending"}
