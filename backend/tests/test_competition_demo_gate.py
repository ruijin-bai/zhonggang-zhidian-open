from app.api.v1 import router_system
from app.core.security import hash_password
from app.db.models.user import User
from app.services.auth.auth_service import issue_token


async def test_competition_demo_capability_defaults_off_and_requires_auth(session):
    user = User(user_id="demo_gate_r4", username="demo_gate_r4", hashed_password=hash_password("Password@123"), role="R4")
    session.add(user)
    await session.commit()
    result = await router_system.competition_capabilities(user)
    assert result.status_code == 200
    assert b'"competition_demo_enabled":false' in result.body


async def test_competition_demo_capability_can_be_explicitly_enabled(session, monkeypatch):
    monkeypatch.setattr(router_system.settings, "COMPETITION_DEMO_ENABLED", True)
    result = await router_system.competition_capabilities(object())
    assert b'"competition_demo_enabled":true' in result.body
