from __future__ import annotations

import httpx

from app.core.security import hash_password
from app.db.models.trial import TrialBenchmarkRecord, TrialUsageEvent
from app.db.models.user import User
from app.db.models.qa import QASession
from app.main import app
from app.services.auth.auth_service import issue_token
from app.services.trial import build_trial_summary


async def _user(session, user_id: str, role: str) -> User:
    user = User(
        user_id=user_id, username=user_id, hashed_password=hash_password("Password@123"),
        role=role, secret_clearance="internal", is_active=True,
    )
    session.add(user)
    await session.commit()
    return user


async def test_trial_summary_uses_only_explicit_real_trial_events(session):
    user = await _user(session, "trial_user", "R1")
    session.add(QASession(session_id="real-trial-session", user_id=user.user_id, question="合成测试问题", answer_interpret="合成测试回答"))
    await session.flush()
    session.add_all([
        TrialUsageEvent(user_id=user.user_id, role="R1", session_id="real-trial-session", event_type="qa_completed", result_state="completed", is_trial=True, latency_total_ms=3000, need_human=False),
        TrialUsageEvent(user_id=user.user_id, role="R1", session_id="real-trial-session", event_type="feedback_like", is_trial=True),
        TrialUsageEvent(user_id=user.user_id, role="R1", event_type="qa_completed", result_state="completed", is_trial=False, latency_total_ms=1),
        TrialBenchmarkRecord(scenario="境外审批", participant_id_hash="a" * 64, manual_duration_seconds=120, ai_duration_seconds=30, manual_success=True, ai_success=True, manual_source_found=True, ai_source_found=True),
    ])
    await session.commit()
    result = await build_trial_summary(session)
    assert result["trial_participants"] == 1
    assert result["real_questions"] == 1
    assert result["avg_total_latency_ms"] == 3000
    assert result["efficiency_improvement_rate"] == 0.75


async def test_trial_api_role_boundaries_and_csv_export(session):
    r1 = await _user(session, "trial_r1", "R1")
    r2 = await _user(session, "trial_r2", "R2")
    r4 = await _user(session, "trial_r4", "R4")
    headers = lambda user: {"Authorization": f"Bearer {issue_token(user)}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        event = await client.post("/api/v1/trial/events", json={"event_type": "qa_started", "is_trial": True}, headers=headers(r1))
        denied_summary = await client.get("/api/v1/trial/summary", headers=headers(r1))
        allowed_summary = await client.get("/api/v1/trial/summary", headers=headers(r2))
        denied_benchmark = await client.post("/api/v1/trial/benchmark", json={
            "scenario": "境外审批", "participant_id_hash": "b" * 64,
            "manual_duration_seconds": 100, "ai_duration_seconds": 20,
            "manual_success": True, "ai_success": True,
            "manual_source_found": True, "ai_source_found": True,
        }, headers=headers(r2))
        created = await client.post("/api/v1/trial/benchmark", json={
            "scenario": "境外审批", "participant_id_hash": "c" * 64,
            "manual_duration_seconds": 100, "ai_duration_seconds": 20,
            "manual_success": True, "ai_success": True,
            "manual_source_found": True, "ai_source_found": True,
        }, headers=headers(r4))
        exported = await client.get("/api/v1/trial/export", headers=headers(r4))
    assert event.status_code == 200
    assert denied_summary.status_code == 403
    assert allowed_summary.status_code == 200
    assert denied_benchmark.status_code == 403
    assert created.status_code == 200
    assert "participant_id_hash" in exported.content.decode("utf-8-sig")
