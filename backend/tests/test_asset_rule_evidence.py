"""Synthetic V2 rule evidence regressions; these are not business trial samples."""
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.db.models.asset import AssetDocument, AssetVersion, AssetVersionDocument, DocumentParseRun
from app.db.models.org import OrgUnit
from app.db.models.permission import Permission
from app.db.models.rule import DecisionRule
from app.main import app
from app.services.auth.auth_service import issue_token
from test_compound_retrieval import _seed_compound_unit
from test_rule_case_workflow import _seed_user


async def _setup(session):
    employee = await _seed_user(session, "synthetic-v2-employee", "R1", "/a")
    reviewer = await _seed_user(session, "synthetic-v2-reviewer", "R2", "/a")
    curator = await _seed_user(session, "synthetic-v2-curator", "R3", "/a")
    # Give each role only internal clearance to test document and unit gates.
    for user in [employee, reviewer, curator]:
        user.secret_clearance = "internal"
    for permission in (await session.execute(select(Permission))).scalars():
        permission.secret_level = "internal"
    session.add(OrgUnit(org_id="synthetic-v2-owner", name="合成测试责任部门", path="/a"))
    await session.flush()
    employee.org_id = "synthetic-v2-owner"
    unit, asset = await _seed_compound_unit(session)
    asset.owner_org = "synthetic-v2-owner"
    version = await session.get(AssetVersion, unit.version_id)
    version.effective_date = date.today() - timedelta(days=1)
    link = (await session.execute(select(AssetVersionDocument).where(AssetVersionDocument.version_id == version.version_id))).scalar_one()
    document = await session.get(AssetDocument, link.document_id)
    parse = (await session.execute(select(DocumentParseRun).where(DocumentParseRun.document_id == document.document_id))).scalar_one()
    await session.flush()
    return employee, reviewer, curator, unit, asset, version, link, document, parse


def _headers(user):
    return {"Authorization": f"Bearer {issue_token(user)}"}


def _rule_body(unit, **overrides):
    values = {
        "rule_key": "synthetic-v2-boundary", "scenario": "contract_change", "source_kind": "asset",
        "asset_version_id": unit.version_id, "retrieval_unit_id": unit.unit_id, "currency": "USD",
        "org_scope": "/a", "approver_path": ["合成测试区域审批"], "required_materials": ["合成测试申请材料"],
    }
    values.update(overrides)
    return values


async def test_v2_sources_create_review_and_case_cent_boundary_keep_original_evidence(session):
    employee, reviewer, curator, unit, asset, version, *_ = await _setup(session)
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        sources = await client.get("/api/v1/rules/sources", headers=_headers(curator))
        assert sources.status_code == 200, sources.text
        selected = next(row for row in sources.json()["data"]["sources"] if row.get("asset_version_id") == version.version_id)
        assert selected["source_kind"] == "asset"
        source_units = await client.get("/api/v1/rules/sources", params={"source_kind": "asset", "asset_version_id": version.version_id}, headers=_headers(curator))
        assert source_units.status_code == 200, source_units.text
        assert source_units.json()["data"]["total"] == 1
        evidence = source_units.json()["data"]["units"][0]
        assert evidence["retrieval_unit_id"] == unit.unit_id
        assert evidence["content_hash"] == unit.content_hash
        assert evidence["source_locator"] == "page:3/article:12"

        rule_ids = []
        for suffix, bounds, path in [
            ("at", {"amount_max_minor": 50_000_000, "max_inclusive": True}, ["合成测试区域审批"]),
            ("above", {"amount_min_minor": 50_000_000, "min_inclusive": False}, ["合成测试总部审批"]),
        ]:
            created = await client.post("/api/v1/rules", json=_rule_body(unit, rule_key=f"synthetic-{suffix}", approver_path=path, **bounds), headers=_headers(curator))
            assert created.status_code == 200, created.text
            rule = created.json()["data"]
            assert rule["status"] == "pending_review"
            assert rule["source_kind"] == "asset"
            assert rule["asset_version_id"] == version.version_id
            approved = await client.post(f"/api/v1/rules/{rule['rule_id']}/review", json={"approved": True, "note": "合成测试：核对来源与分值边界，不作为业务签审"}, headers=_headers(reviewer))
            assert approved.status_code == 200, approved.text
            assert approved.json()["data"]["status"] == "current"
            rule_ids.append(rule["rule_id"])

        for amount, index, approver in [(50_000_000, 0, "合成测试区域审批"), (50_000_001, 1, "合成测试总部审批")]:
            created_case = await client.post("/api/v1/cases", json={"title": "合成测试分值边界事项", "scenario": "contract_change", "org_path": "/a", "amount_minor": amount, "currency": "USD"}, headers=_headers(employee))
            assert created_case.status_code == 200, created_case.text
            case_id = created_case.json()["data"]["case_id"]
            evaluated = await client.post(f"/api/v1/cases/{case_id}/evaluate", headers=_headers(employee))
            assert evaluated.status_code == 200, evaluated.text
            case = evaluated.json()["data"]
            assert case["need_human"] is False
            assert case["status"] == "assessed"
            snapshot = case["decision_snapshot"]
            assert snapshot["matched_rule_ids"] == [rule_ids[index]]
            assert snapshot["approval_path"] == [approver]
            source = snapshot["evidence"][0]
            assert source["source_kind"] == "asset"
            assert source["file_id"] == asset.asset_id
            assert source["asset_version_id"] == version.version_id
            assert source["retrieval_unit_id"] == unit.unit_id
            assert source["content_hash"] == unit.content_hash
            assert source["source_locator"] == "page:3/article:12"


@pytest.mark.parametrize("gap", ["issue_no", "effective_date", "owner_org", "domain", "non_normative", "expired", "isolated", "document_secret", "unit_secret", "foreign_org", "draft", "not_ready", "obsolete_parse"])
async def test_ineligible_v2_evidence_cannot_be_selected_created_or_executed(session, gap):
    employee, _reviewer, curator, unit, asset, version, link, document, parse = await _setup(session)
    if gap == "issue_no": version.issue_no = ""
    elif gap == "effective_date": version.effective_date = None
    elif gap == "owner_org": asset.owner_org = None
    elif gap == "domain": asset.domain = "*"
    elif gap == "non_normative": link.normative = False
    elif gap == "expired": version.expiry_date = date.today() - timedelta(days=1)
    elif gap == "isolated": unit.status = "isolated"
    elif gap == "document_secret": document.secret_level = "confidential"
    elif gap == "unit_secret": unit.secret_level = "confidential"
    elif gap == "foreign_org": asset.org_path = "/b"
    elif gap == "draft": version.release_state = "draft"
    elif gap == "not_ready": version.ingestion_state = "pending"
    elif gap == "obsolete_parse": parse.is_current = False
    # Simulate an untrusted/stale persisted rule as well as rejecting new input.
    # This synthetic row is created in the test DB, not through business APIs.
    session.add(DecisionRule(rule_key="synthetic-stale", scenario="contract_change", source_kind="asset", asset_version_id=version.version_id, retrieval_unit_id=unit.unit_id, status="current", approver_path=["不得输出的测试路径"]))
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        sources = await client.get("/api/v1/rules/sources", headers=_headers(curator))
        assert sources.status_code == 200, sources.text
        assert not any(row.get("asset_version_id") == version.version_id for row in sources.json()["data"]["sources"])
        units = await client.get("/api/v1/rules/sources", params={"source_kind": "asset", "asset_version_id": version.version_id}, headers=_headers(curator))
        assert units.status_code == 200, units.text
        assert units.json()["data"]["units"] == []
        assert units.json()["data"]["total"] == 0
        created = await client.post("/api/v1/rules", json=_rule_body(unit), headers=_headers(curator))
        assert created.status_code == 400, created.text
        case = await client.post("/api/v1/cases", json={"title": "合成测试无效证据事项", "scenario": "contract_change", "org_path": "/a", "amount_minor": 1, "currency": "USD"}, headers=_headers(employee))
        assert case.status_code == 200, case.text
        result = await client.post(f"/api/v1/cases/{case.json()['data']['case_id']}/evaluate", headers=_headers(employee))
        assert result.status_code == 200, result.text
        snapshot = result.json()["data"]["decision_snapshot"]
        assert snapshot["reason_code"] == "no_active_rule"
        assert snapshot["need_human"] is True
        assert snapshot["matched_rule_ids"] == snapshot["evidence"] == snapshot["approval_path"] == []


@pytest.mark.parametrize("changes", [
    {"file_id": "legacy-file"}, {"clause_id": "legacy-clause"},
    {"source_kind": "regulation"},
    {"source_kind": "regulation", "file_id": "legacy-file", "clause_id": "legacy-clause"},
    {"source_kind": "unknown"}, {"asset_version_id": None}, {"retrieval_unit_id": None},
])
async def test_mixed_or_incomplete_source_identity_is_rejected_before_rule_creation(session, changes):
    _employee, _reviewer, curator, unit, *_rest = await _setup(session)
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/rules", json=_rule_body(unit, **changes), headers=_headers(curator))
    assert response.status_code == 422, response.text
