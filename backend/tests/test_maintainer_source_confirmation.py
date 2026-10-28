"""Single-maintainer usability without fabricated official source metadata."""
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select

from app.db.models.clause import Clause
from app.db.models.permission import Permission
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.main import app
from app.services.auth.auth_service import issue_token
from app.services.governance_state import is_authority_verified, source_verification, valid_source_confirmation
from test_regulation_upload import _seed_r_role, _login, _upload


def _statement(**changes):
    value = {"kind": "maintainer", "confirmed": True, "actor_id": "maintainer",
        "confirmed_at": datetime.now(timezone.utc).isoformat(), "note": "本人确认上传资料可靠"}
    value.update(changes)
    return value


def test_confirmation_preserves_unknown_official_metadata_and_does_not_claim_department_review():
    source = RegulationFile(file_id="owned", title="本人上传资料", version="v1", status="current",
        regulation_code="", domain="*", source_confirmation=_statement(file_id="owned", version="v1", object_key=None))
    assert is_authority_verified(source)
    assert source_verification(source) == "maintainer"
    assert source.effective_date is source.owner_org is source.reviewed_by is None
    assert source.regulation_code == ""
    source.version = "v2"
    assert not is_authority_verified(source)
    assert not valid_source_confirmation(_statement(confirmed=False))
    assert not valid_source_confirmation(_statement(actor_id=""))
    assert not valid_source_confirmation(_statement(confirmed_at="2026-10-01T00:00:00"))


async def test_batch_confirmation_makes_missing_metadata_sources_usable_without_filling_fields(session):
    user = await _seed_r_role(session, "source-confirm-user", "test-source-password", "R3")
    for identifier in ("source-one", "source-two"):
        session.add(RegulationFile(file_id=identifier, title=identifier, regulation_code="", version="v1", status="current", domain="*"))
        await session.flush()
        session.add(Clause(file_id=identifier, clause_id=identifier + "-clause", content="这是可核对的制度原文", status="current"))
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        headers = {"Authorization": f"Bearer {issue_token(user)}"}
        result = await client.post("/api/v1/regulations/source-confirmations", headers=headers, json={"file_ids": ["source-one", "source-two"]})
        assert result.status_code == 200, result.text
        assert result.json()["data"]["count"] == 2
        rows = (await client.get("/api/v1/regulations", headers=headers)).json()["data"]
        assert all(row["source_verification"] == "maintainer" and row["authority_verified"] for row in rows)
        assert all(row["clause_count"] == 1 for row in rows)
        assert all(row["effective_date"] is None and row["owner_org"] is None and row["regulation_code"] == "" for row in rows)
        sources = (await client.get("/api/v1/rules/sources", headers=headers)).json()["data"]
        assert {row["file_id"] for row in sources["sources"]} == {"source-one", "source-two"}


async def test_batch_is_atomic_when_one_document_has_no_readable_text(session):
    user = await _seed_r_role(session, "source-empty-user", "test-source-password", "R3")
    session.add_all([RegulationFile(file_id="readable", title="有原文", status="current"), RegulationFile(file_id="empty", title="无原文", status="current")])
    await session.flush()
    session.add(Clause(clause_id="readable-clause", file_id="readable", content="可核对的原文", status="current"))
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post("/api/v1/regulations/source-confirmations", headers={"Authorization": f"Bearer {issue_token(user)}"}, json={"file_ids": ["readable", "empty"]})
    assert result.status_code == 400, result.text
    await session.refresh(await session.get(RegulationFile, "readable"))
    assert (await session.get(RegulationFile, "readable")).source_confirmation == {}


async def test_confirmation_does_not_expand_organisation_or_employee_rights(session):
    user = User(user_id="local-maintainer", username="local-maintainer", hashed_password="unused", role="R3", secret_clearance="internal")
    session.add_all([user, Permission(role="R3", org_scope="/hq/ab", domain="*", secret_level="internal"),
        RegulationFile(file_id="other-branch", title="其他部门资料", org_path="/hq/a", status="current")])
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post("/api/v1/regulations/source-confirmations", headers={"Authorization": f"Bearer {issue_token(user)}"}, json={"file_ids": ["other-branch"]})
    assert result.status_code == 404, result.text
    assert (await session.get(RegulationFile, "other-branch")).source_confirmation == {}


async def test_upload_with_personal_confirmation_needs_no_official_number_date_or_department(session):
    await _seed_r_role(session, "single-maintainer", "test-source-password", "R3")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        token = await _login(client, "single-maintainer", "test-source-password")
        result = await _upload(client, token, "personal.txt", "第一条 本文件仅为合成产品测试。\n第二条 用户可对照原文准备资料。".encode(), "text/plain",
            regulation_code="", effective_date="", owner_org="", domain="*", source_confirmed="true", source_note="合成验证：本人确认来源，不代表部门审核")
        assert result.status_code == 200, result.text
        assert result.json()["data"]["status"] == "current"
    source = await session.get(RegulationFile, result.json()["data"]["file_id"])
    await session.refresh(source)
    assert source.effective_date is source.owner_org is source.reviewed_by is None
    assert source.regulation_code == "" and source_verification(source) == "maintainer"


async def test_rule_can_be_confirmed_by_maintainer_without_changing_roles_or_model_inference(session):
    user = await _seed_r_role(session, "rule-maintainer", "test-source-password", "R3")
    source = RegulationFile(file_id="rule-personal-source", title="合成办理规定", version="v1", status="current", domain="*", source_confirmation=_statement())
    session.add(source)
    await session.flush()
    session.add(Clause(file_id=source.file_id, clause_id="rule-personal-clause", clause_no="第一条", content="合成事项应提交合成材料，经合成人工环节核对。", status="current"))
    await session.commit()
    body = {"rule_key": "维护者合成规则", "scenario": "safety", "file_id": source.file_id, "clause_id": "rule-personal-clause",
        "approver_path": ["合成人工核对"], "required_materials": ["合成材料"], "activate_now": True, "activation_note": "本人已对照合成原文确认，测试不作为实际业务批准"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.post("/api/v1/rules", headers={"Authorization": f"Bearer {issue_token(user)}"}, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["status"] == "current"
    assert result.json()["data"]["reviewed_by"] == user.user_id
    assert result.json()["data"]["review_note"].startswith("[维护者确认]")


async def test_self_confirmed_replacement_retains_case_snapshot_and_notifies_only_readers(session):
    from app.db.models.business_case import BusinessCase
    from app.db.models.impact import ChangeImpactRun, ChangeImpactItem
    from app.db.models.push import PushRecord, PushReceipt
    from app.db.models.rule import DecisionRule
    from app.services.regulation.versioning import publish_regulation, announce_regulation_publication
    actor = await _seed_r_role(session, "update-maintainer", "test-source-password", "R3")
    unreadable = User(user_id="update-no-clearance", username="update-no-clearance", hashed_password="unused",
        role="R1", secret_clearance="public", is_active=True)
    session.add_all([unreadable, Permission(role="R1", org_scope="/", domain="*", secret_level="internal")])
    old = RegulationFile(file_id="old-personal", title="合成旧版", version="v1", status="current", domain="*", regulation_code="")
    new = RegulationFile(file_id="new-personal", title="合成新版", version="v2", status="pending_review", domain="*",
        regulation_code="", replaces_file_id=old.file_id, source_confirmation=_statement(actor_id=actor.user_id))
    session.add_all([old, new])
    await session.flush()
    session.add_all([Clause(clause_id="old-personal-clause", file_id=old.file_id, clause_no="第一条", content="合成旧办理路径", status="current"),
        Clause(clause_id="new-personal-clause", file_id=new.file_id, clause_no="第一条", content="合成新办理路径", status="current")])
    await session.flush()
    rule = DecisionRule(rule_id="old-personal-rule", rule_key="旧版合成规则", scenario="safety", status="current",
        file_id=old.file_id, clause_id="old-personal-clause", approver_path=["旧环节"], required_materials=["旧材料"])
    snapshot = {"evidence": [{"clause_id": "old-personal-clause"}], "matched_rule_ids": [rule.rule_id], "approver_path": ["旧环节"]}
    case = BusinessCase(case_id="historical-personal-case", case_no="synthetic-update-only", requester_id=actor.user_id,
        scenario="safety", title="合成历史事项", status="confirmed", decision_snapshot=snapshot)
    session.add_all([rule, case])
    await session.flush()
    await publish_regulation(session, new)
    await announce_regulation_publication(session, new)
    await announce_regulation_publication(session, new)
    await session.commit()
    await session.refresh(rule)
    await session.refresh(case)
    assert old.status == "replaced" and rule.status == "retired"
    assert case.decision_snapshot == snapshot and case.status == "confirmed"
    assert new.reviewed_by is None
    pushes = list((await session.scalars(select(PushRecord).where(PushRecord.file_id == new.file_id))).all())
    assert len(pushes) == 1
    recipients = set((await session.scalars(select(PushReceipt.user_id).where(PushReceipt.push_id == pushes[0].push_id))).all())
    assert recipients == {actor.user_id}
    impact = await session.scalar(select(ChangeImpactRun).where(ChangeImpactRun.new_file_id == new.file_id))
    assert impact.summary["historical_case_review"] == 1
    assert await session.scalar(select(ChangeImpactItem.item_id).where(ChangeImpactItem.impact_id == impact.impact_id,
        ChangeImpactItem.object_id == case.case_id))


async def test_quality_count_uses_same_confirmation_state_as_directory(session):
    user = await _seed_r_role(session, "quality-maintainer", "test-source-password", "R4")
    session.add_all([
        RegulationFile(file_id="quality-confirmed", title="已确认", version="v1", status="current", domain="*",
            source_confirmation=_statement(file_id="quality-confirmed", version="v1")),
        RegulationFile(file_id="quality-stale", title="版本变更未确认", version="v2", status="current", domain="*",
            source_confirmation=_statement(file_id="quality-stale", version="v1")),
        RegulationFile(file_id="quality-pending", title="尚未启用", version="v1", status="pending_review", domain="*",
            source_confirmation=_statement(file_id="quality-pending", version="v1")),
    ])
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        result = await client.get("/api/v1/dashboard/quality", headers={"Authorization": f"Bearer {issue_token(user)}"})
    assert result.status_code == 200, result.text
    assert result.json()["data"]["regulation_current"] == 2
    assert result.json()["data"]["regulation_authority_verified"] == 1


@pytest.mark.parametrize("boundary", [{"amount_min_minor": 0}, {"amount_max_minor": 100}])
def test_money_boundary_needs_explicit_currency_but_non_money_rule_does_not(boundary):
    from pydantic import ValidationError
    from app.schemas.rule import DecisionRuleCreate
    base = {"rule_key": "合成流程", "scenario": "safety", "file_id": "synthetic-source",
        "clause_id": "synthetic-clause", "approver_path": ["合成核对"]}
    assert DecisionRuleCreate(**base).currency == "*"
    with pytest.raises(ValidationError, match="须明确币种"):
        DecisionRuleCreate(**base, **boundary, currency="")
    with pytest.raises(ValidationError, match="须明确币种"):
        DecisionRuleCreate(**base, **boundary, currency="*")
    assert DecisionRuleCreate(**base, **boundary, currency="usd").currency == "USD"
