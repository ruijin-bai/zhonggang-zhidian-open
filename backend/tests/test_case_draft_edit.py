"""Owned draft corrections must never evaluate stale facts or overwrite approval."""
from __future__ import annotations

import json
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.db.models.business_case import BusinessCase
from app.db.models.permission import Permission
from app.db.models.org import OrgUnit
from app.db.models.user import User
from app.main import app
from app.services.auth.auth_service import issue_token


async def _identity(session, name: str, role: str, scope: str, *, bind_org: bool | None = None):
    user = User(user_id=name, username=name, hashed_password=hash_password("Test-only-123"), role=role, secret_clearance="internal")
    if (role == "R1" if bind_org is None else bind_org):
        org = (await session.execute(select(OrgUnit).where(OrgUnit.path == scope).limit(1))).scalar_one_or_none()
        if org is None:
            org = OrgUnit(org_id=f"{name}_org", name=f"测试组织{scope}", path=scope)
            session.add(org)
            await session.flush()
        user.org_id = org.org_id
    session.add_all([user, Permission(role=role, org_scope=scope, secret_level="internal", domain="*")])
    await session.commit()
    return user, {"Authorization": f"Bearer {issue_token(user)}"}


def _body(**changes):
    return {"scenario": "contract_change", "title": "修正后的变更事项", "org_path": "/project-a", "project_code": None,
            "amount_minor": 750001, "currency": "usd", "facts": {"urgent": False, "description": "已核对新金额"}, **changes}


async def test_owned_draft_edit_preserves_identity_and_evaluates_updated_facts(session):
    from app.db.models.org import OrgUnit
    owner, headers = await _identity(session, "draft_owner", "R1", "/project-a")
    org = await session.get(OrgUnit, owner.org_id)
    org.name = "合成项目A"
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = (await client.post("/api/v1/cases", headers=headers, json=_body(amount_minor=100, project_code="OLD"))).json()["data"]
        case_id = created["case_id"]
        edited = await client.put(f"/api/v1/cases/{case_id}", headers=headers,
                                  json=_body(facts={"urgent": False, "description": "已核对新金额", "项目类型": "建设工程",
                                                    "is_overseas": False, "review_count": 2}))
        assert edited.status_code == 200, edited.text
        data = edited.json()["data"]
        assert (data["case_id"], data["case_no"]) == (case_id, created["case_no"])
        assert data["amount_minor"] == 750001 and data["currency"] == "USD"
        assert data["project_code"] is None
        assert data["org_name"] == "合成项目A"
        assert data["status"] == "draft" and data["decision_snapshot"] == {}
        evaluated = await client.post(f"/api/v1/cases/{case_id}/evaluate", headers=headers)
        assert evaluated.status_code == 200, evaluated.text
        result = evaluated.json()["data"]
        assert result["amount_minor"] == 750001
        assert result["facts"]["description"] == "已核对新金额"
        assert result["facts"]["项目类型"] == "建设工程"
        assert result["facts"]["is_overseas"] is False and result["facts"]["review_count"] == 2
        assert result["decision_snapshot"] and result["status"] == "review_required"
        mine = (await client.get("/api/v1/cases/mine", headers=headers)).json()["data"]
        assert len(mine) == 1 and mine[0]["org_name"] == "合成项目A"


async def test_returned_case_edit_clears_stale_review_but_preserves_audit(session):
    owner, headers = await _identity(session, "returned_owner", "R1", "/project-a")
    case = BusinessCase(case_id="returned_case", case_no="BC-returned", requester_id=owner.user_id, scenario="contract_change",
                        title="退回事项", org_path="/project-a", status="returned", amount_minor=100, currency="USD",
                        facts={"description": "旧事实"}, decision_summary="旧结论", decision_snapshot={"approval_path": ["旧审批人"]},
                        review_note="请修正金额")
    session.add(case)
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put("/api/v1/cases/returned_case", headers=headers, json=_body(amount_minor=None, currency=None))
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["status"] == "draft" and data["decision_summary"] is None and data["decision_snapshot"] == {}
        assert data["review_note"] is None and data["reviewed_by"] is None
        assert data["amount_minor"] is None and data["currency"] is None
        evaluated = await client.post("/api/v1/cases/returned_case/evaluate", headers=headers)
        assert evaluated.status_code == 200
        assert "旧审批人" not in json.dumps(evaluated.json(), ensure_ascii=False)
    from app.db.models.audit import AuditLog
    audit = (await session.execute(select(AuditLog).where(AuditLog.action == "case.updated"))).scalar_one()
    assert "请修正金额" in audit.detail and "旧审批人" in audit.detail


@pytest.mark.parametrize("currency", ["USD", None])
async def test_currency_only_case_keeps_amount_unknown_and_uses_explicit_currency(session, currency):
    from app.db.models.clause import Clause
    from app.db.models.regulation import RegulationFile
    from app.db.models.rule import DecisionRule

    owner, headers = await _identity(session, "currency_only_owner", "R1", "/project-a")
    file = RegulationFile(file_id="currency_only_file", regulation_code="SYNTH-CURRENCY-ONLY",
                          title="合成币种流程依据", version="v1", status="current", org_path="/project-a",
                          secret_level="internal", domain="工程", owner_org=owner.org_id, effective_date=date.today())
    clause = Clause(clause_id="currency_only_clause", file_id=file.file_id, clause_no="第一条",
                    content="美元事项按合成流程办理；没有金额门槛。", status="current", secret_level="internal")
    rule = DecisionRule(rule_key="currency-only-rule", scenario="safety", source_kind="regulation",
                        file_id=file.file_id, clause_id=clause.clause_id, status="current", org_scope="/project-a",
                        currency="USD", conditions={}, approver_path=["合成业务确认"])
    session.add_all([file, clause, rule])
    await session.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        body = _body(scenario="safety", title="合成无金额币种事项", amount_minor=None, currency=currency)
        created = await client.post("/api/v1/cases", headers=headers, json=body)
        assert created.status_code == 200, created.text
        data = created.json()["data"]
        assert data["amount_minor"] is None and data["currency"] == currency
        case_id = data["case_id"]
        edited = await client.put(f"/api/v1/cases/{case_id}", headers=headers, json=body)
        assert edited.status_code == 200, edited.text
        assert edited.json()["data"]["case_id"] == case_id
        assert edited.json()["data"]["amount_minor"] is None
        assert edited.json()["data"]["currency"] == currency
        evaluated = await client.post(f"/api/v1/cases/{case_id}/evaluate", headers=headers)
        assert evaluated.status_code == 200, evaluated.text
        result = evaluated.json()["data"]
        assert result["amount_minor"] is None
        if currency:
            assert result["status"] == "assessed" and result["need_human"] is False
            assert result["decision_snapshot"]["approval_path"] == ["合成业务确认"]
            assert result["decision_snapshot"]["matched_rule_ids"] == [rule.rule_id]
            assert "已启用的制度规则" in result["decision_summary"]
        else:
            assert result["need_human"] is True
            assert result["decision_snapshot"]["missing_fields"] == ["currency"]


@pytest.mark.parametrize("status", ["confirmed", "assessed", "review_required"])
async def test_final_or_pending_case_cannot_be_edited_or_re_evaluated(session, status):
    owner, headers = await _identity(session, "locked_owner", "R1", "/project-a")
    case = BusinessCase(case_id="locked_case", case_no="BC-locked", requester_id=owner.user_id, scenario="contract_change",
                        title="已形成结论", org_path="/project-a", status=status, facts={}, decision_snapshot={"approval_path": ["保留审批人"]})
    session.add(case)
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        edited = await client.put("/api/v1/cases/locked_case", headers=headers, json=_body())
        assert edited.status_code == 400
        evaluated = await client.post("/api/v1/cases/locked_case/evaluate", headers=headers)
        assert evaluated.status_code == 400
        actual = (await client.get("/api/v1/cases/locked_case", headers=headers)).json()["data"]
        assert actual["status"] == status and actual["decision_snapshot"]["approval_path"] == ["保留审批人"]


async def test_other_user_even_admin_cannot_edit_owned_draft(session):
    owner, headers = await _identity(session, "private_owner", "R1", "/project-a")
    _, admin_headers = await _identity(session, "other_admin", "R4", "/")
    session.add(BusinessCase(case_id="private_draft", case_no="BC-private", requester_id=owner.user_id,
                            scenario="contract_change", title="本人草稿", org_path="/project-a", status="draft", facts={}))
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        forbidden = await client.put("/api/v1/cases/private_draft", headers=admin_headers, json=_body())
        assert forbidden.status_code == 403
        invalid = await client.put("/api/v1/cases/private_draft", headers=headers, json=_body(amount_minor=-1))
        assert invalid.status_code == 422
        original = (await client.get("/api/v1/cases/private_draft", headers=headers)).json()["data"]
        assert original["title"] == "本人草稿"


async def test_review_scope_respects_path_segments_for_queue_detail_update_and_evaluate(session):
    owner, owner_headers = await _identity(session, "scope_owner", "R1", "/project-a")
    _, review_headers = await _identity(session, "scope_reviewer", "R2", "/project-a")
    session.add_all([
        BusinessCase(case_id="in_scope_case", case_no="BC-in", requester_id=owner.user_id, scenario="contract_change",
                     title="子项目事项", org_path="/project-a/child", status="review_required", facts={}),
        BusinessCase(case_id="prefix_sibling_case", case_no="BC-out", requester_id=owner.user_id, scenario="contract_change",
                     title="前缀相似事项", org_path="/project-ab", status="review_required", facts={}),
        BusinessCase(case_id="prefix_draft", case_no="BC-out-draft", requester_id=owner.user_id, scenario="contract_change",
                     title="前缀相似草稿", org_path="/project-ab", status="draft", facts={}),
    ])
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        queue = await client.get("/api/v1/cases/review-queue", headers=review_headers)
        assert queue.status_code == 200
        assert [row["case_id"] for row in queue.json()["data"]] == ["in_scope_case"]
        assert (await client.get("/api/v1/cases/in_scope_case", headers=review_headers)).status_code == 200
        assert (await client.get("/api/v1/cases/prefix_sibling_case", headers=review_headers)).status_code == 403
        denied_review = await client.post("/api/v1/cases/prefix_sibling_case/review", headers=review_headers,
                                         json={"confirmed": False, "note": "无权复核"})
        assert denied_review.status_code == 403
        assert (await client.put("/api/v1/cases/prefix_draft", headers=owner_headers, json=_body(org_path="/project-ab"))).status_code == 403
        assert (await client.post("/api/v1/cases/prefix_draft/evaluate", headers=owner_headers)).status_code == 403


async def test_manual_review_guidance_uses_the_same_snapshot_keys_as_rule_results(session):
    _, owner_headers = await _identity(session, "review_owner", "R1", "/project-a")
    _, reviewer_headers = await _identity(session, "guidance_reviewer", "R2", "/")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = (await client.post("/api/v1/cases", headers=owner_headers, json=_body())).json()["data"]
        case_id = created["case_id"]
        assert (await client.post(f"/api/v1/cases/{case_id}/evaluate", headers=owner_headers)).status_code == 200
        reviewed = await client.post(f"/api/v1/cases/{case_id}/review", headers=reviewer_headers,
                                    json={"confirmed": True, "note": "已核对原文", "approver_path": ["项目部", "区域公司"],
                                          "required_materials": ["变更申请", "金额测算"]})
        assert reviewed.status_code == 200, reviewed.text
        snapshot = reviewed.json()["data"]["decision_snapshot"]
        assert snapshot["approval_path"] == ["项目部", "区域公司"]
        assert snapshot["materials"] == ["变更申请", "金额测算"]


async def test_case_context_counts_only_effective_authoritative_accessible_rule_sources(session):
    from app.db.models.clause import Clause
    from app.db.models.org import OrgUnit
    from app.db.models.regulation import RegulationFile
    from app.db.models.rule import DecisionRule
    owner, headers = await _identity(session, "context_owner", "R1", "/project-a")
    org = await session.get(OrgUnit, owner.org_id)
    org.name = "项目A"
    await session.flush()
    owner.org_id = org.org_id
    today = date.today()
    for index, properties in enumerate([
        {},
        {"effective_date": today + timedelta(days=1)},
        {"owner_org": None},
        {"scope": "/project-ab"},
        {"secret_level": "secret"},
        {"rule_effective_from": today + timedelta(days=1)},
    ]):
        file = RegulationFile(file_id=f"context_file_{index}", regulation_code=f"CHEC-CTX-{index}", title=f"场景依据{index}",
                              version="v1", status="current", org_path="/", secret_level="internal", domain="工程",
                              owner_org=properties.get("owner_org", org.org_id), effective_date=properties.get("effective_date", today))
        clause = Clause(clause_id=f"context_clause_{index}", file_id=file.file_id, clause_no="第一条", content="按既定路径办理。",
                        secret_level=properties.get("secret_level", "internal"), status="current")
        rule = DecisionRule(rule_key=f"context_rule_{index}", scenario="contract_change", source_kind="regulation", file_id=file.file_id,
                            clause_id=clause.clause_id, status="current", org_scope=properties.get("scope", "/project-a"), currency="USD",
                            approver_path=["项目部"], effective_from=properties.get("rule_effective_from"),
                            conditions={"项目类型": "建设工程", "procurement_method": ["公开招标", "邀请招标"], "is_overseas": True,
                                        "review_count": 2, "urgent": True, "复杂条件": {"mode": "special"}} if index == 0
                            else {f"被过滤字段{index}": "不得披露"})
        session.add_all([file, clause, rule])
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/cases/context", headers=headers)
        assert response.status_code == 200, response.text
        context = response.json()["data"]
        assert context["org_name"] == "项目A"
        assert context["rule_counts"] == {"contract_change": 1}
        fields = {field["key"]: field for field in context["fact_fields"]["contract_change"]}
        assert set(fields) == {"项目类型", "procurement_method", "is_overseas", "review_count", "复杂条件"}
        assert fields["项目类型"]["options"] == [{"value": "建设工程", "label": "建设工程"}]
        assert fields["procurement_method"]["label"] == "采购方式"
        assert fields["procurement_method"]["options"] == [{"value": "公开招标", "label": "公开招标"}, {"value": "邀请招标", "label": "邀请招标"}]
        assert fields["is_overseas"]["kind"] == "boolean"
        assert fields["is_overseas"]["options"] == [{"value": True, "label": "是"}, {"value": False, "label": "否"}]
        assert fields["review_count"]["kind"] == "number" and fields["review_count"]["options"][0]["value"] == 2
        assert fields["复杂条件"]["kind"] == "manual" and fields["复杂条件"]["options"] == []


async def test_missing_specific_rule_fact_blocks_generic_result_and_scope_is_segment_bound(session):
    from app.db.models.clause import Clause
    from app.db.models.org import OrgUnit
    from app.db.models.regulation import RegulationFile
    from app.db.models.rule import DecisionRule
    _, headers = await _identity(session, "condition_owner", "R1", "/")
    org = OrgUnit(org_id="condition_org", name="合成规则责任组织", path="/project-a")
    session.add_all([org, OrgUnit(name="合成子项目", path="/project-a/child"), OrgUnit(name="合成前缀相似组织", path="/project-ab")])
    await session.flush()
    file = RegulationFile(file_id="condition_file", regulation_code="CHEC-SYNTH-CONDITION", title="合成采购依据",
                          version="v1", status="current", org_path="/", secret_level="internal", domain="工程",
                          owner_org=org.org_id, effective_date=date.today())
    clause = Clause(clause_id="condition_clause", file_id=file.file_id, clause_no="第一条", content="采购方式须按事实核对。",
                    secret_level="internal", status="current")
    common = dict(scenario="procurement", source_kind="regulation", file_id=file.file_id, clause_id=clause.clause_id,
                  status="current", org_scope="/project-a", currency="*", approver_path=["项目业务复核"])
    session.add_all([file, clause,
                     DecisionRule(rule_key="specific-procurement", conditions={"procurement_method": "公开招标"}, **common),
                     DecisionRule(rule_key="generic-procurement", conditions={}, **common)])
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        async def evaluate(org_path, facts):
            created = (await client.post("/api/v1/cases", headers=headers,
                                        json=_body(scenario="procurement", org_path=org_path, facts=facts))).json()["data"]
            response = await client.post(f"/api/v1/cases/{created['case_id']}/evaluate", headers=headers)
            assert response.status_code == 200, response.text
            return response.json()["data"]
        incomplete = await evaluate("/project-a", {})
        assert incomplete["need_human"] is True and incomplete["status"] == "review_required"
        result = incomplete["decision_snapshot"]
        assert result["reason_code"] == "missing_facts"
        assert result["missing_fields"] == ["procurement_method"]
        assert result["approval_path"] == [] and result["matched_rule_ids"] == []
        supplied = await evaluate("/project-a/child", {"procurement_method": "公开招标"})
        assert supplied["need_human"] is False
        assert supplied["decision_snapshot"]["approval_path"] == ["项目业务复核"]
        sibling = await evaluate("/project-ab", {"procurement_method": "公开招标"})
        assert sibling["need_human"] is True
        assert sibling["decision_snapshot"]["reason_code"] == "no_matching_rule"
        assert sibling["decision_snapshot"]["matched_rule_ids"] == []


async def test_confirmation_requires_meaningful_path_and_note_but_return_does_not(session):
    _, owner_headers = await _identity(session, "boundary_owner", "R1", "/project-a")
    _, reviewer_headers = await _identity(session, "boundary_reviewer", "R2", "/")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = (await client.post("/api/v1/cases", headers=owner_headers, json=_body())).json()["data"]
        case_id = created["case_id"]
        assert (await client.post(f"/api/v1/cases/{case_id}/evaluate", headers=owner_headers)).status_code == 200
        for body in [
            {"confirmed": True, "note": "已核对"},
            {"confirmed": True, "note": "已核对", "approver_path": [" ", "\t"]},
            {"confirmed": True, "note": " \n ", "approver_path": ["业务复核"]},
            {"confirmed": False, "note": "   "},
        ]:
            invalid = await client.post(f"/api/v1/cases/{case_id}/review", headers=reviewer_headers, json=body)
            assert invalid.status_code == 422, invalid.text
            unchanged = (await client.get(f"/api/v1/cases/{case_id}", headers=owner_headers)).json()["data"]
            assert unchanged["status"] == "review_required" and unchanged["reviewed_by"] is None
        confirmed = await client.post(f"/api/v1/cases/{case_id}/review", headers=reviewer_headers,
                                      json={"confirmed": True, "note": "  已核对正式口径  ",
                                            "approver_path": ["  项目业务复核 ", " "], "required_materials": ["  金额说明  ", ""]})
        assert confirmed.status_code == 200, confirmed.text
        actual = confirmed.json()["data"]
        assert actual["status"] == "confirmed" and actual["review_note"] == "已核对正式口径"
        assert actual["decision_snapshot"]["approval_path"] == ["项目业务复核"]
        assert actual["decision_snapshot"]["materials"] == ["金额说明"]
        returned_case = (await client.post("/api/v1/cases", headers=owner_headers, json=_body())).json()["data"]
        returned_id = returned_case["case_id"]
        assert (await client.post(f"/api/v1/cases/{returned_id}/evaluate", headers=owner_headers)).status_code == 200
        returned = await client.post(f"/api/v1/cases/{returned_id}/review", headers=reviewer_headers,
                                    json={"confirmed": False, "note": "  请补充金额来源  "})
        assert returned.status_code == 200, returned.text
        assert returned.json()["data"]["status"] == "returned"
        assert returned.json()["data"]["review_note"] == "请补充金额来源"
        empty_material_case = BusinessCase(case_id="clear_material_case", case_no="BC-clear-material",
                                           requester_id=created["requester_id"], scenario="contract_change", title="清空旧材料",
                                           org_path="/project-a", status="review_required", facts={},
                                           decision_snapshot={"materials": ["旧材料"], "required_materials": ["旧材料"]})
        session.add(empty_material_case)
        await session.commit()
        cleared = await client.post("/api/v1/cases/clear_material_case/review", headers=reviewer_headers,
                                    json={"confirmed": True, "note": "已确认不需此项旧材料", "approver_path": ["业务复核"]})
        assert cleared.status_code == 200, cleared.text
        cleared_snapshot = cleared.json()["data"]["decision_snapshot"]
        assert cleared_snapshot["materials"] == [] and cleared_snapshot["required_materials"] == []
        assert cleared_snapshot["manual_review"]["required_materials"] == []


async def test_create_and_update_require_real_bound_and_authorised_organisations(session):
    _, headers = await _identity(session, "org_boundary_owner", "R1", "/project-a")
    session.add_all([OrgUnit(name="子项目", path="/project-a/child"), OrgUnit(name="相似前缀其他组织", path="/project-ab")])
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post("/api/v1/cases", headers=headers, json=_body(org_path=None))
        assert created.status_code == 200, created.text
        actual = created.json()["data"]
        assert actual["org_path"] == "/project-a" and actual["org_name"] == "测试组织/project-a"
        for target, expected in [("/project-ab", 403), ("/project-a/not-registered", 400)]:
            rejected = await client.post("/api/v1/cases", headers=headers, json=_body(org_path=target))
            assert rejected.status_code == expected, rejected.text
            edited = await client.put(f"/api/v1/cases/{actual['case_id']}", headers=headers, json=_body(org_path=target))
            assert edited.status_code == expected, edited.text
        unchanged = (await client.get(f"/api/v1/cases/{actual['case_id']}", headers=headers)).json()["data"]
        assert unchanged["org_path"] == "/project-a"
        permitted = await client.put(f"/api/v1/cases/{actual['case_id']}", headers=headers, json=_body(org_path="/project-a/child"))
        assert permitted.status_code == 200 and permitted.json()["data"]["org_name"] == "子项目"
        _, unbound_headers = await _identity(session, "unbound_employee", "R1", "/project-a", bind_org=False)
        unbound = await client.post("/api/v1/cases", headers=unbound_headers, json=_body())
        assert unbound.status_code == 400
        _, admin_headers = await _identity(session, "bound_admin", "R4", "/", bind_org=True)
        authorised_admin = await client.post("/api/v1/cases", headers=admin_headers, json=_body(org_path="/project-ab"))
        assert authorised_admin.status_code == 200, authorised_admin.text
        invented_admin = await client.post("/api/v1/cases", headers=admin_headers, json=_body(org_path="/unregistered"))
        assert invented_admin.status_code == 400
