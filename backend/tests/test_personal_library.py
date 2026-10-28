"""Synthetic private-library API contracts; no business trial or model call."""
from datetime import date, datetime, timedelta, timezone
import json

import httpx
from sqlalchemy import select

from app.db.models.asset import AssetVersion
from app.db.models.audit import AuditLog
from app.db.models.clause import Clause
from app.db.models.feedback import QAFeedback
from app.db.models.permission import Permission
from app.db.models.qa import QACitation, QASession
from app.db.models.regulation import RegulationFile
from app.db.session import SessionLocal
from app.main import app
from app.services.auth.auth_service import issue_token
from test_compound_retrieval import _seed_compound_unit
from test_read_authorization import _seed_user

BASE = "/api/v1/me/library"


async def seed(session, role="R1"):
    user = await _seed_user(session, "personal_owner", role)
    other = await _seed_user(session, "personal_other", role)
    permission = Permission(role=role, org_scope="/", secret_level="internal", domain="*")
    file = RegulationFile(file_id="personal_file", title="常用制度100%_核对", status="current", version="v1")
    session.add_all([permission, file])
    await session.flush()
    clause = Clause(clause_id="personal_clause", file_id=file.file_id, clause_no="第一条", content="测试正文", status="current")
    session.add(clause)
    await session.commit()
    return user, other, permission, file, clause


def headers(user):
    return {"Authorization": f"Bearer {issue_token(user)}"}


def client(user):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers(user))


def target(file, **values):
    return {"source_kind": "regulation", "target_id": file.file_id, **values}


async def test_favorite_persists_across_database_sessions_and_cancellation_is_private(session):
    owner, other, _, file, _ = await seed(session)
    async with client(owner) as api:
        for _ in range(2):
            assert (await api.post(BASE + "/favorite", json=target(file, saved=True))).status_code == 200
    async with client(other) as api:
        await api.post(BASE + "/favorite", json=target(file, saved=True))
    # A new ORM session and a new HTTP client read committed data, not a UI cache.
    async with SessionLocal() as persisted:
        events = list((await persisted.execute(select(AuditLog).where(AuditLog.action == "library.favorite.add"))).scalars())
        assert len(events) == 2
    async with client(owner) as api:
        assert (await api.get(BASE + "/favorites")).json()["data"]["items"][0]["target_id"] == file.file_id
        await api.post(BASE + "/favorite", json=target(file, saved=False))
        assert (await api.get(BASE + "/favorites")).json()["data"]["total"] == 0
        assert (await api.get(BASE + "/state", params=target(file))).json()["data"]["saved"] is False
    async with client(other) as api:
        assert (await api.get(BASE + "/favorites")).json()["data"]["total"] == 1


async def test_recent_keeps_latest_position_deduplicates_and_revalidates_clause(session):
    owner, _, _, file, clause = await seed(session)
    second = Clause(clause_id="personal_second", file_id=file.file_id, content="第二条测试", status="current")
    session.add(second)
    await session.commit()
    async with client(owner) as api:
        for _ in range(2):
            assert (await api.post(BASE + "/reading", json=target(file, clause_id=clause.clause_id))).status_code == 200
        await api.post(BASE + "/reading", json=target(file, clause_id=second.clause_id))
        values = (await api.get(BASE + "/recent")).json()["data"]
        assert values["total"] == 1
        assert values["items"][0]["resume_clause_id"] == second.clause_id
        assert (await api.get(BASE + "/favorites")).json()["data"]["total"] == 0
        second.secret_level = "secret"
        await session.commit()
        value = (await api.get(BASE + "/state", params=target(file))).json()["data"]["reading"]
        assert value["resume_clause_id"] is None
        assert "personal_second" not in json.dumps(value)
    async with SessionLocal() as persisted:
        assert len(list((await persisted.execute(select(AuditLog).where(AuditLog.action == "library.read"))).scalars())) == 2


async def test_wrong_resource_position_and_hidden_resource_cannot_be_saved(session):
    owner, _, _, file, clause = await seed(session)
    hidden = RegulationFile(file_id="personal_hidden", title="保密资料不能泄露", secret_level="secret")
    different = RegulationFile(file_id="personal_other_file", title="另一个制度")
    session.add_all([hidden, different])
    await session.commit()
    async with client(owner) as api:
        assert (await api.post(BASE + "/favorite", json=target(hidden, saved=True))).status_code == 404
        assert (await api.get(BASE + "/state", params=target(hidden))).status_code == 404
        assert (await api.post(BASE + "/reading", json=target(different, clause_id=clause.clause_id))).status_code == 404
        assert (await api.get(BASE + "/recent")).json()["data"]["total"] == 0


async def test_saved_resources_recheck_current_permission_expiry_and_literal_search(session):
    owner, _, permission, file, _ = await seed(session, role="R4")
    now = datetime.now(timezone.utc)
    hidden = RegulationFile(file_id="saved_secret", title="隐藏标题和标识", secret_level="secret")
    expired = RegulationFile(file_id="saved_expired", title="失效制度", expiry_date=date.today() - timedelta(days=1))
    future = RegulationFile(file_id="saved_future", title="未生效制度", effective_date=date.today() + timedelta(days=1))
    session.add_all([hidden, expired, future])
    for row in (file, hidden, expired, future):
        session.add(AuditLog(actor_id=owner.user_id, action="library.favorite.add", target_type="library.regulation", target_id=row.file_id, created_at=now))
    await session.commit()
    async with client(owner) as api:
        values = (await api.get(BASE + "/favorites", params={"q": "%_", "limit": 1})).json()["data"]
        assert values["total"] == 1
        assert len(values["items"]) == 1
        assert "saved_secret" not in json.dumps(values)
        assert "saved_expired" not in json.dumps(values)
        assert (await api.get(BASE + "/favorites", params={"offset": 1})).json()["data"]["items"] == []
        file.secret_level = "secret"
        await session.commit()
        assert (await api.get(BASE + "/favorites")).json()["data"]["total"] == 0
        # Removing an owned preference after access was withdrawn is harmless.
        assert (await api.post(BASE + "/favorite", json=target(file, saved=False))).status_code == 200
        permission.secret_level = "secret"
        owner.secret_clearance = "secret"
        await session.commit()
        values = (await api.get(BASE + "/favorites")).json()["data"]
        assert {item["target_id"] for item in values["items"]} == {hidden.file_id}


async def test_v2_current_version_changes_clear_stale_reading_but_keep_private_favorite(session):
    owner, _, _, _, _ = await seed(session)
    unit, asset = await _seed_compound_unit(session)
    await session.commit()
    body = {"source_kind": "asset", "target_id": asset.asset_id, "asset_version_id": unit.version_id}
    async with client(owner) as api:
        assert (await api.post(BASE + "/favorite", json={**body, "saved": True})).status_code == 200
        assert (await api.post(BASE + "/reading", json={**body, "clause_id": unit.unit_id})).status_code == 200
        assert (await api.get(BASE + "/state", params=body)).json()["data"]["reading"]["resume_clause_id"] == unit.unit_id
        old = await session.get(AssetVersion, unit.version_id)
        old.release_state = "replaced"
        new = AssetVersion(asset_id=asset.asset_id, version_label="v3", release_state="current", ingestion_state="ready")
        session.add(new)
        await session.commit()
        state = (await api.get(BASE + "/state", params=body)).json()["data"]
        assert state["saved"] is True
        assert state["reading"]["version_changed"] is True
        assert state["reading"]["resume_clause_id"] is None
        assert state["reading"]["asset_version_id"] == new.version_id
        assert (await api.post(BASE + "/reading", json={**body, "clause_id": unit.unit_id})).status_code == 404
        asset.status = "archived"
        await session.commit()
        assert (await api.get(BASE + "/favorites")).json()["data"]["total"] == 0


async def test_answer_favorites_are_owned_non_evaluation_and_all_citations_current_readable(session):
    owner, other, _, file, clause = await seed(session)
    unit, _ = await _seed_compound_unit(session)
    secret = Clause(clause_id="private_secret_clause", file_id=file.file_id, secret_level="secret", content="隐藏正文")
    session.add(secret)
    sessions = [
        QASession(session_id="saved_answer", user_id=owner.user_id, question="测试收藏问题", answer_interpret="已保存测试回答"),
        QASession(session_id="saved_v2_answer", user_id=owner.user_id, question="V2问题", answer_interpret="V2测试回答"),
        QASession(session_id="saved_eval", user_id=owner.user_id, question="评测不能入个人列表", answer_interpret="评测", is_evaluation=True),
        QASession(session_id="saved_empty", user_id=owner.user_id, question="未回答", answer_interpret="  "),
        QASession(session_id="saved_hidden_answer", user_id=owner.user_id, question="隐藏问题", answer_interpret="禁止回显片段"),
        QASession(session_id="saved_other_answer", user_id=other.user_id, question="他人的咨询", answer_interpret="他人内容"),
    ]
    session.add_all(sessions)
    await session.flush()
    for value in sessions:
        session.add(QAFeedback(session_id=value.session_id, user_id=owner.user_id, type="favorite"))
    session.add(QAFeedback(session_id="saved_answer", user_id=owner.user_id, type="favorite"))
    for qa, source in (("saved_answer", clause.clause_id), ("saved_v2_answer", unit.unit_id), ("saved_hidden_answer", clause.clause_id), ("saved_hidden_answer", secret.clause_id)):
        session.add(QACitation(session_id=qa, clause_id=source, excerpt="synthetic"))
    await session.commit()
    async with client(owner) as api:
        values = (await api.get(BASE + "/answer-favorites")).json()["data"]
        assert values["total"] == 2
        assert {item["session_id"] for item in values["items"]} == {"saved_answer", "saved_v2_answer"}
        assert "禁止回显片段" not in json.dumps(values, ensure_ascii=False)
        assert (await api.get(BASE + "/answer-favorites", params={"q": "V2", "limit": 1})).json()["data"]["total"] == 1
        unit.status = "isolated"
        file.status = "replaced"
        await session.commit()
        assert (await api.get(BASE + "/answer-favorites")).json()["data"]["total"] == 0


async def test_remove_answer_favorite_only_changes_owned_favorites(session):
    owner, other, _, _, _ = await seed(session)
    own = QASession(session_id="owned_to_remove", user_id=owner.user_id, question="测试", answer_interpret="测试")
    foreign = QASession(session_id="foreign_to_keep", user_id=other.user_id, question="其他人", answer_interpret="其他人")
    session.add_all([own, foreign])
    await session.flush()
    session.add_all([
        QAFeedback(session_id=own.session_id, user_id=owner.user_id, type="favorite"),
        QAFeedback(session_id=own.session_id, user_id=owner.user_id, type="favorite"),
        QAFeedback(session_id=own.session_id, user_id=owner.user_id, type="like"),
        QAFeedback(session_id=own.session_id, user_id=other.user_id, type="favorite"),
        QAFeedback(session_id=foreign.session_id, user_id=other.user_id, type="favorite"),
    ])
    await session.commit()
    async with client(owner) as api:
        assert (await api.post(BASE + "/answer-favorites/remove", json={"session_id": foreign.session_id})).status_code == 404
        assert (await api.post(BASE + "/answer-favorites/remove", json={"session_id": own.session_id})).status_code == 200
        assert (await api.get(BASE + "/answer-favorites")).json()["data"]["total"] == 0
    async with SessionLocal() as persisted:
        rows = list((await persisted.execute(select(QAFeedback))).scalars())
        assert len(rows) == 3
        assert {(row.session_id, row.user_id, row.type) for row in rows} == {
            (own.session_id, owner.user_id, "like"), (own.session_id, other.user_id, "favorite"),
            (foreign.session_id, other.user_id, "favorite"),
        }


async def test_personal_library_requires_active_authenticated_account(session):
    owner, _, _, _, _ = await seed(session)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api:
        assert (await api.get(BASE + "/favorites")).status_code == 401
        owner.is_active = False
        await session.commit()
        assert (await api.get(BASE + "/recent", headers=headers(owner))).status_code == 401
