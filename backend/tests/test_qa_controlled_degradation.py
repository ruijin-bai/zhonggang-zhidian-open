"""P0: real model/vector failures must return an auditable degraded QA state."""
from __future__ import annotations

import json

import httpx
from sqlalchemy import select

from app.core.exceptions import EmbeddingError
from app.core.security import hash_password
from app.db.models.audit import AuditLog
from app.db.models.permission import Permission
from app.db.models.qa import QASession
from app.db.models.user import User
from app.main import app
from app.utils.metrics import metrics_payload


async def _seed_r1(session) -> None:
    session.add_all(
        [
            User(
                user_id="u_degraded_r1",
                username="degraded_r1",
                hashed_password=hash_password("Zhonggang@123"),
                role="R1",
                secret_clearance="internal",
                is_active=True,
            ),
            Permission(
                perm_id="perm_degraded_r1",
                role="R1",
                org_scope="/",
                secret_level="internal",
                domain="*",
            ),
        ]
    )
    await session.commit()


async def test_embedding_failure_returns_auditable_degraded_response(session, monkeypatch) -> None:
    await _seed_r1(session)

    async def fail_retrieve(*_args, **_kwargs):
        raise EmbeddingError("provider connection failed")

    monkeypatch.setattr("app.services.qa_service.RetrieverService.retrieve", fail_retrieve)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"username": "degraded_r1", "password": "Zhonggang@123"},
        )
        token = login.json()["data"]["access_token"]
        response = await client.post(
            "/api/v1/qa/ask",
            json={"question": "境外项目变更款由谁审批？"},
            headers={"Authorization": f"Bearer {token}"},
        )
        stream = await client.post(
            "/api/v1/qa/ask/stream",
            json={"question": "境外项目变更款由谁审批？"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["degraded"] is True
    assert data["degraded_reason"] == "embedding_unavailable"
    assert data["need_human"] is True
    assert data["citations"] == []
    assert "未生成制度结论" in data["answer_interpret"]

    assert stream.status_code == 200, stream.text
    events = [json.loads(line) for line in stream.text.splitlines() if line]
    done = next(event for event in events if event["type"] == "done")
    assert done["degraded_reason"] == "embedding_unavailable"
    assert not any(event["type"] == "error" for event in events)

    saved = await session.get(QASession, data["session_id"])
    assert saved is not None
    assert saved.degraded is True
    assert saved.need_human is True
    audit = (
        await session.execute(
            select(AuditLog).where(AuditLog.target_id == data["session_id"])
        )
    ).scalar_one()
    assert audit.action == "qa.ask.degraded"
    assert "reason=embedding_unavailable" in (audit.detail or "")
    assert b'zg_qa_degraded_total' in metrics_payload()
