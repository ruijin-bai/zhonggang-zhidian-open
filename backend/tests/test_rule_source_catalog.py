"""Prefer complete mapped rule sources, keeping splits and explicit old readers."""
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.db.models.asset import AssetVersion, AssetVersionDocument
from app.db.models.clause import Clause
from app.db.models.org import OrgUnit
from app.db.models.permission import Permission
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.main import app
from app.services.auth.auth_service import issue_token
from test_compound_retrieval import _seed_compound_unit


def _statement(**identity):
    return {"kind": "maintainer", "confirmed": True, "actor_id": "catalog-curator",
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "note": "合成测试来源确认，不作为真实业务依据", **identity}


async def _legacy(session):
    user = User(user_id="catalog-curator", username="catalog-curator", hashed_password="unused",
                role="R3", secret_clearance="internal")
    file = RegulationFile(file_id="catalog-legacy", title="合成同名资料", version="v1", status="current",
                          org_path="/a", secret_level="internal", domain="*", regulation_code="",
                          source_confirmation=_statement(file_id="catalog-legacy", version="v1", object_key=None))
    session.add_all([user, Permission(role="R3", org_scope="/a", secret_level="internal", domain="*"),
                     OrgUnit(org_id="catalog-org", name="合成组织", path="/a"), file])
    await session.flush()
    clause = Clause(clause_id="catalog-clause", file_id=file.file_id, clause_no="第一条",
                    content="合成原文应按明确环节办理。", status="current", secret_level="internal")
    session.add(clause)
    await session.flush()
    return {"Authorization": f"Bearer {issue_token(user)}"}, file, clause


async def _asset(session, file, *, mapped=True, title="合成同名资料"):
    unit, asset = await _seed_compound_unit(session)
    asset.title, asset.org_path, asset.domain = title, "/a", "*"
    version = await session.get(AssetVersion, unit.version_id)
    version.legacy_file_id = file.file_id if mapped else None
    # The source is personally confirmed while official fields remain unknown.
    version.version_metadata = {"source_manifest_fingerprint": "synthetic-manifest",
        "source_confirmation": _statement(version_id=version.version_id, manifest_fingerprint="synthetic-manifest")}
    await session.flush()
    return asset, version, unit


async def _sources(client, headers):
    response = await client.get("/api/v1/rules/sources", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]["sources"]


async def test_complete_asset_is_default_but_unmapped_same_title_and_explicit_readers_remain(session):
    headers, file, clause = await _legacy(session)
    clause.content = "安全事项须提交合成材料并由合成环节审批。"
    mirrored, version, unit = await _asset(session, file)
    independent, independent_version, _ = await _asset(session, file, mapped=False)
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        rows = await _sources(client, headers)
        assert {(row["source_kind"], row["file_id"]) for row in rows} == {
            ("asset", mirrored.asset_id), ("asset", independent.asset_id)}
        assert rows[0]["title"] == rows[1]["title"]
        assert any(row.get("asset_version_id") == version.version_id for row in rows)
        assert any(row.get("asset_version_id") == independent_version.version_id for row in rows)

        # Selection deduplication does not invalidate explicit evidence identities.
        for params, identity in [({"source_kind": "regulation", "file_id": file.file_id}, clause.clause_id),
                                 ({"source_kind": "asset", "asset_version_id": version.version_id}, unit.unit_id)]:
            read = await client.get("/api/v1/rules/sources", params=params, headers=headers)
            assert read.status_code == 200, read.text
            assert read.json()["data"]["total"] == 1
            assert read.json()["data"]["units"][0]["clause_id"] == identity
        candidates = await client.get("/api/v1/rules/coverage", headers=headers)
        assert candidates.status_code == 200, candidates.text
        old_candidate = next(item for item in candidates.json()["data"]["items"] if item["clause_id"] == clause.clause_id)
        assert old_candidate["file_id"] == file.file_id and old_candidate["file_title"] == file.title
        created = await client.post("/api/v1/rules", headers=headers, json={
            "rule_key": "hidden-mirror-explicit-rule", "scenario": "safety", "source_kind": "asset",
            "asset_version_id": version.version_id, "retrieval_unit_id": unit.unit_id,
            "org_scope": "/a", "approver_path": ["合成办理环节"], "activate_now": True,
            "activation_note": "合成测试对照原文确认"})
        assert created.status_code == 200, created.text
        legacy_created = await client.post("/api/v1/rules", headers=headers, json={
            "rule_key": "hidden-legacy-candidate-rule", "scenario": "safety", "source_kind": "regulation",
            "file_id": old_candidate["file_id"], "clause_id": old_candidate["clause_id"],
            "org_scope": "/a", "approver_path": ["合成环节审批"], "activate_now": True,
            "activation_note": "合成测试核对旧候选原文"})
        assert legacy_created.status_code == 200, legacy_created.text
        listed = await client.get("/api/v1/rules", headers=headers)
        assert listed.status_code == 200, listed.text
        persisted = listed.json()["data"]
        assert any(row["asset_version_id"] == version.version_id and row["file_id"] == mirrored.asset_id for row in persisted)
        assert any(row["source_kind"] == "regulation" and row["file_id"] == file.file_id and row["clause_id"] == clause.clause_id for row in persisted)


@pytest.mark.parametrize("gap", ["empty", "no_current_clause", "clause_secret", "foreign_org", "pending", "future", "expired", "unconfirmed", "malformed_confirmation", "stale_confirmation"])
async def test_usable_asset_remains_when_original_is_not_a_usable_source(session, gap):
    headers, file, clause = await _legacy(session)
    asset, version, _unit = await _asset(session, file)
    if gap == "empty": clause.content = "  \n  "
    elif gap == "no_current_clause": clause.status = "isolated"
    elif gap == "clause_secret": clause.secret_level = "secret"
    elif gap == "foreign_org": file.org_path = "/b"
    elif gap == "pending": file.status = "pending_review"
    elif gap == "future": file.effective_date = date.today() + timedelta(days=1)
    elif gap == "expired": file.expiry_date = date.today() - timedelta(days=1)
    elif gap == "unconfirmed": file.source_confirmation = {}
    elif gap == "malformed_confirmation": file.source_confirmation = {"confirmed": True}
    elif gap == "stale_confirmation": file.source_confirmation = _statement(version="old-version")
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        rows = await _sources(client, headers)
    assert len(rows) == 1
    assert rows[0]["source_kind"] == "asset" and rows[0]["file_id"] == asset.asset_id
    assert rows[0]["asset_version_id"] == version.version_id


@pytest.mark.parametrize("original_readable", [True, False])
async def test_each_usable_split_asset_remains_without_assuming_original_coverage(session, original_readable):
    headers, file, clause = await _legacy(session)
    if not original_readable: clause.content = " \n\t\r "
    first, first_version, _ = await _asset(session, file, title="合成子制度一")
    second, second_version, _ = await _asset(session, file, title="合成子制度二")
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        rows = await _sources(client, headers)
    assert {(row["file_id"], row["asset_version_id"]) for row in rows} == {
        (first.asset_id, first_version.version_id), (second.asset_id, second_version.version_id)}


@pytest.mark.parametrize("original_readable", [True, False])
@pytest.mark.parametrize("gap", ["blocked", "isolated", "non_normative", "unconfirmed"])
async def test_unusable_mirror_never_replaces_original_or_becomes_fallback(session, original_readable, gap):
    headers, file, clause = await _legacy(session)
    _asset_row, version, unit = await _asset(session, file)
    if not original_readable: clause.content = ""
    if gap == "blocked": version.ingestion_state = "blocked"
    elif gap == "isolated": unit.status = "isolated"
    elif gap == "unconfirmed": version.version_metadata = {}
    elif gap == "non_normative":
        link = (await session.execute(select(AssetVersionDocument).where(AssetVersionDocument.version_id == version.version_id))).scalar_one()
        link.normative = False
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        rows = await _sources(client, headers)
    assert {(row["source_kind"], row["file_id"]) for row in rows} == (
        {("regulation", file.file_id)} if original_readable else set())
