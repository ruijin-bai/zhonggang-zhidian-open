"""Auth login & permission-boundary tests (T03).

Service-level:
  * authenticate() returns None on wrong password / inactive account, and the
    user on correct credentials.
  * issue_token() produces a non-empty JWT.

API-level (httpx ASGITransport, sqlite + mock — no Docker needed):
  * POST /api/v1/auth/login with wrong password → 401 (code 40101).
  * R1 employee calling an R3/R4-only endpoint (POST /api/v1/push/notify) → 403
    (code 40301), proving role gating at the HTTP boundary.
"""
from __future__ import annotations

import httpx
from sqlalchemy import select

from app.api.v1 import router_auth
from app.core.security import hash_password
from app.db.models.permission import Permission
from app.db.models.feedback import QAFeedback
from app.db.models.qa import QASession
from app.db.models.user import User
from app.main import app
from app.services.auth.auth_service import authenticate, issue_token


async def _seed_user(session, username, password, role="R1", secret_clearance="internal", active=True):
    user = User(
        user_id=f"u_{username}", username=username,
        hashed_password=hash_password(password),
        role=role, secret_clearance=secret_clearance, is_active=active,
    )
    session.add(user)
    await session.commit()
    return user


async def test_authenticate_wrong_password_returns_none(session):
    await _seed_user(session, "alice", "Zhonggang@123", role="R4")
    assert await authenticate(session, "alice", "wrong-password") is None


async def test_authenticate_inactive_user_returns_none(session):
    await _seed_user(session, "bob", "Zhonggang@123", active=False)
    assert await authenticate(session, "bob", "Zhonggang@123") is None


async def test_authenticate_success_returns_user(session):
    await _seed_user(session, "carol", "Zhonggang@123", role="R4")
    user = await authenticate(session, "carol", "Zhonggang@123")
    assert user is not None
    assert user.username == "carol"


async def test_issue_token_non_empty(session):
    user = await _seed_user(session, "dave", "Zhonggang@123", role="R4")
    assert issue_token(user)


async def test_login_api_wrong_password_401(session):
    await _seed_user(session, "erin", "Zhonggang@123", role="R4")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/auth/login", json={"username": "erin", "password": "nope"}
        )
    assert resp.status_code == 401
    assert resp.json()["code"] == 40101


async def test_demo_identity_login_is_explicitly_gated(session, monkeypatch):
    await _seed_user(session, "admin", "stored-password", role="R4")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        disabled = await client.get("/api/v1/auth/demo-identities")
        assert disabled.status_code == 200
        assert disabled.json()["data"] == {"enabled": False, "identities": []}

        monkeypatch.setattr(router_auth.settings, "DEMO_LOGIN_ENABLED", True)
        monkeypatch.setattr(router_auth.settings, "DEMO_LOGIN_PASSWORD", "DevOnly@123")
        identities = await client.get("/api/v1/auth/demo-identities")
        assert identities.status_code == 200
        rows = identities.json()["data"]["identities"]
        assert {row["username"] for row in rows} == {"employee", "reviewer", "kbadmin", "admin"}
        assert {row["password"] for row in rows} == {"DevOnly@123"}

        login = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "DevOnly@123"},
        )
        assert login.status_code == 200
        assert login.json()["data"]["user"]["role"] == "R4"


async def test_r1_cannot_access_push_notify_403(session):
    await _seed_user(session, "frank", "Zhonggang@123", role="R1")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/login", json={"username": "frank", "password": "Zhonggang@123"}
        )
        assert login.status_code == 200
        token = login.json()["data"]["access_token"]
        resp = await client.post(
            "/api/v1/push/notify",
            json={"file_id": "any"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40301


async def test_qa_session_and_feedback_are_limited_to_session_owner(session):
    """A valid token must not allow reading or writing another user's QA record."""
    owner = await _seed_user(session, "qa_owner", "Zhonggang@123")
    other = await _seed_user(session, "qa_other", "Zhonggang@123")
    qa = QASession(
        session_id="qa_owned_session",
        user_id=owner.user_id,
        question="变更款由谁审批？",
        answer_interpret="须按制度审批。",
        confidence=0.9,
    )
    session.add(qa)
    await session.commit()

    owner_headers = {"Authorization": f"Bearer {issue_token(owner)}"}
    other_headers = {"Authorization": f"Bearer {issue_token(other)}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        owner_detail = await client.get("/api/v1/qa/session/qa_owned_session", headers=owner_headers)
        foreign_detail = await client.get("/api/v1/qa/session/qa_owned_session", headers=other_headers)
        foreign_feedback = await client.post(
            "/api/v1/qa/feedback",
            json={"session_id": "qa_owned_session", "type": "like"},
            headers=other_headers,
        )
        owner_feedback = await client.post(
            "/api/v1/qa/feedback",
            json={"session_id": "qa_owned_session", "type": "like"},
            headers=owner_headers,
        )

    assert owner_detail.status_code == 200
    assert owner_detail.json()["data"]["session_id"] == "qa_owned_session"
    assert foreign_detail.status_code == 404
    assert foreign_detail.json()["code"] == 40401
    assert foreign_feedback.status_code == 404
    assert foreign_feedback.json()["code"] == 40401
    assert owner_feedback.status_code == 200
    assert owner_feedback.json()["code"] == 0
    feedback = list((await session.execute(select(QAFeedback))).scalars())
    assert len(feedback) == 1
    assert feedback[0].user_id == owner.user_id
