"""Compound publication, real state transitions and source-access boundaries."""
from datetime import date, timedelta

import httpx
from sqlalchemy import select

from app.db.models.asset import AssetDocument, AssetVersion, AssetVersionDocument, ContentNode, DocumentParseRun, KnowledgeAsset, RetrievalUnit, RetrievalUnitSource
from app.db.models.audit import AuditLog
from app.db.models.org import OrgUnit
from app.db.models.permission import Permission
from app.db.models.user import User
from app.main import app
from app.services.auth.auth_service import issue_token


async def user(session, role, *, scope="/", clearance="secret", domain="*"):
    row = User(user_id=f"pub_{role}", username=f"pub_{role}", hashed_password="test-only",
               role=role, secret_clearance=clearance)
    session.add_all([row, Permission(role=role, org_scope=scope, secret_level=clearance, domain=domain)])
    await session.flush()
    return {"Authorization": f"Bearer {issue_token(row)}"}


async def package(session, *, state="draft", scope="/", secret="internal", parse_status="succeeded", citable=True, effective=None, expiry=None):
    owner = await session.get(OrgUnit, "pub_owner")
    if owner is None:
        session.add(OrgUnit(org_id="pub_owner", name="正式责任部门", path="/hq/a"))
        await session.flush()
    asset = KnowledgeAsset(asset_type="regulation", title="资料发布验收制度", business_code="正式发文-2026-01",
                           owner_org="pub_owner", domain="工程", org_path=scope, secret_level=secret)
    session.add(asset); await session.flush()
    version = AssetVersion(asset_id=asset.asset_id, version_label="v1", release_state=state, ingestion_state="ready",
                           issue_no="正式发文-2026-01", effective_date=effective or date.today(), expiry_date=expiry)
    document = AssetDocument(filename="正式原文.txt", title="正文", object_key="local://publication-test.txt",
                             sha256="a"*64, mime="text/plain", secret_level=secret, size_bytes=123)
    session.add_all([version, document]); await session.flush()
    run = DocumentParseRun(document_id=document.document_id, parser_name="test", status=parse_status,
                           is_current=True, source_hash=document.sha256)
    session.add(run); await session.flush()
    session.add_all([
        AssetVersionDocument(version_id=version.version_id, document_id=document.document_id,
                             role="normative_body", mandatory=True, normative=True),
        ContentNode(document_id=document.document_id, parse_run_id=run.parse_run_id, order_path="0001", ordinal=1,
                    node_type="article", text="第一条 发布前必须核对原文。", normalized_text="第一条 发布前必须核对原文。",
                    source_locator="text:1", is_citable=citable, content_hash="b"*64),
    ])
    await session.commit()
    return asset, version, document, run


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_submit_reject_resubmit_publish_and_audit(session):
    curator, reviewer, employee = await user(session,"R3"), await user(session,"R2"), await user(session,"R1")
    asset, version, document, _ = await package(session)
    async with client() as c:
        assert (await c.get(f"/api/v1/assets/{asset.asset_id}",headers=employee)).status_code == 404
        assert (await c.get(f"/api/v1/assets/{asset.asset_id}",headers=reviewer)).status_code == 404
        submitted = await c.post(f"/api/v1/assets/versions/{version.version_id}/submit",headers=curator)
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["data"]["release_state"] == "pending_review"
        queue = await c.get("/api/v1/assets/reviews/pending",headers=reviewer)
        assert queue.json()["data"][0]["version_id"] == version.version_id
        preview = await c.get(f"/api/v1/assets/{asset.asset_id}",headers=reviewer)
        assert preview.json()["data"]["versions"][0]["publication_gate"]["publishable"]
        tree = await c.get(f"/api/v1/assets/documents/{document.document_id}/tree",headers=reviewer)
        assert tree.json()["data"]["nodes"][0]["text"].startswith("第一条")
        assert (await c.post(f"/api/v1/assets/versions/{version.version_id}/review",headers=curator,json={"decision":"approve","note":"越权"})).status_code == 403
        rejected = await c.post(f"/api/v1/assets/versions/{version.version_id}/review",headers=reviewer,json={"decision":"reject","note":"补充核对意见"})
        assert rejected.json()["data"]["release_state"] == "rejected"
        assert (await c.get(f"/api/v1/assets/{asset.asset_id}",headers=employee)).status_code == 404
        assert (await c.post(f"/api/v1/assets/versions/{version.version_id}/submit",headers=curator)).status_code == 200
        approved = await c.post(f"/api/v1/assets/versions/{version.version_id}/review",headers=reviewer,json={"decision":"approve","note":"已核对正式原文和来源字段"})
        assert approved.status_code == 200, approved.text
        assert (await c.get(f"/api/v1/assets/{asset.asset_id}",headers=employee)).status_code == 200
        assert (await c.post(f"/api/v1/assets/versions/{version.version_id}/review",headers=reviewer,json={"decision":"approve","note":"重复审核"})).status_code == 400
    await session.refresh(version)
    assert version.release_state == "current" and version.reviewed_by == "pub_R2"
    actions = (await session.execute(select(AuditLog.action).where(AuditLog.target_id == version.version_id))).scalars().all()
    assert actions.count("asset.submit") == 2 and actions.count("asset.review") == 2


async def test_mandatory_failure_and_missing_citable_content_block_submission(session):
    curator = await user(session,"R3")
    _asset, failed, _doc, _run = await package(session,parse_status="requires_ocr")
    _asset, empty, _doc, _run = await package(session,citable=False)
    async with client() as c:
        for version in (failed,empty):
            r = await c.post(f"/api/v1/assets/versions/{version.version_id}/submit",headers=curator)
            assert r.status_code == 400
            assert r.json()["data"]["errors"]
            await session.refresh(version); assert version.release_state == "draft"


async def test_changed_snapshot_cannot_publish_after_submission(session):
    curator, reviewer = await user(session,"R3"), await user(session,"R2")
    _asset, version, document, run = await package(session)
    async with client() as c:
        assert (await c.post(f"/api/v1/assets/versions/{version.version_id}/submit",headers=curator)).status_code == 200
        assert (await c.post(f"/api/v1/assets/documents/{document.document_id}/parse",headers=curator)).status_code == 400
        run.status = "failed"; await session.commit()
        response = await c.post(f"/api/v1/assets/versions/{version.version_id}/review",headers=reviewer,json={"decision":"approve","note":"核对"})
        assert response.status_code == 400
        await session.refresh(version); assert version.release_state == "pending_review"


async def test_organization_secrecy_domain_and_time_boundaries(session):
    employee = await user(session,"R1",scope="/hq/a/team",clearance="internal",domain="工程")
    curator = await user(session,"R3",scope="/hq/a/team",clearance="internal",domain="工程")
    allowed, _v, document, _ = await package(session,state="current",scope="/hq/a")
    other, other_version, otherdoc, other_run = await package(session,state="current",scope="/hq/b")
    secret, _v, secretdoc, _ = await package(session,state="current",scope="/hq/a",secret="confidential")
    future, _v, futuredoc, _ = await package(session,state="current",scope="/hq/a",effective=date.today()+timedelta(days=3))
    expired, _v, expireddoc, _ = await package(session,state="current",scope="/hq/a",expiry=date.today()-timedelta(days=1))
    different, _v, domaindoc, _ = await package(session,state="current",scope="/hq/a")
    different.domain = "财务"; await session.commit()
    async with client() as c:
        listing = (await c.get("/api/v1/assets",headers=employee)).json()["data"]
        assert {row["asset_id"] for row in listing} == {allowed.asset_id}
        for asset, doc in [(other,otherdoc),(secret,secretdoc),(future,futuredoc),(expired,expireddoc),(different,domaindoc)]:
            assert (await c.get(f"/api/v1/assets/{asset.asset_id}",headers=employee)).status_code == 404
            assert (await c.get(f"/api/v1/assets/documents/{doc.document_id}/tree",headers=employee)).status_code == 404
        assert (await c.get(f"/api/v1/assets/documents/{document.document_id}/tree",headers=employee)).status_code == 200
        forged = await c.get(f"/api/v1/assets/documents/{document.document_id}/tree",params={"parse_run_id":other_run.parse_run_id},headers=curator)
        assert forged.status_code == 404
        assert (await c.patch(f"/api/v1/assets/versions/{other_version.version_id}/metadata",headers=curator,json={"domain":"工程","evidence_note":"越权"})).status_code == 404


async def test_metadata_requires_real_organization_and_revision_preserves_live_files(session):
    curator = await user(session,"R3")
    asset, version, document, run = await package(session,state="current")
    async with client() as c:
        assert (await c.patch(f"/api/v1/assets/versions/{version.version_id}/metadata",headers=curator,json={"issue_no":"新文号","evidence_note":"核对原文"})).status_code == 400
        revision = await c.post(f"/api/v1/assets/versions/{version.version_id}/revision",headers=curator,json={"version_label":"v2"})
        assert revision.status_code == 200, revision.text
        new_id = revision.json()["data"]["version_id"]
        invalid = await c.patch(f"/api/v1/assets/versions/{new_id}/metadata",headers=curator,json={"owner_org":"invented_org","evidence_note":"核对原文"})
        assert invalid.status_code == 400
        valid = await c.patch(f"/api/v1/assets/versions/{new_id}/metadata",headers=curator,json={"owner_org":"pub_owner","issue_no":"正式修订-2026-02","effective_date":date.today().isoformat(),"domain":"财务","evidence_note":"正式原文首页及责任部门确认"})
        assert valid.status_code == 200, valid.text
        current = (await c.get(f"/api/v1/assets/{asset.asset_id}",headers=curator)).json()["data"]
        assert current["domain"] == "工程"
        assert next(v for v in current["versions"] if v["version_id"]==new_id)["domain"]=="财务"
    links = (await session.execute(select(AssetVersionDocument).where(AssetVersionDocument.version_id==new_id))).scalars().all()
    assert len(links)==1 and links[0].document_id != document.document_id
    await session.refresh(version); await session.refresh(run)
    assert version.release_state == "current" and run.is_current


async def test_unknown_legacy_date_is_reference_readable_but_blocks_new_submission(session):
    curator, employee = await user(session,"R3"), await user(session,"R1")
    asset, version, _doc, _run = await package(session,state="current")
    version.effective_date = None; await session.commit()
    async with client() as c:
        detail = await c.get(f"/api/v1/assets/{asset.asset_id}",headers=employee)
        assert detail.status_code==200 and "effective_date" in detail.json()["data"]["versions"][0]["authority_gaps"]
        version.release_state="draft"; await session.commit()
        r=await c.post(f"/api/v1/assets/versions/{version.version_id}/submit",headers=curator)
        assert r.status_code==400


async def test_published_only_does_not_expose_management_versions(session):
    curator=await user(session,"R3")
    allowed, active, _doc, _run=await package(session,state="current")
    draft, _version, _doc, _run=await package(session,state="draft")
    future, _version, _doc, _run=await package(session,state="current",effective=date.today()+timedelta(days=1))
    expired, _version, _doc, _run=await package(session,state="current",expiry=date.today()-timedelta(days=1))
    blocked, blocked_version, _doc, _run=await package(session,state="current")
    blocked_version.ingestion_state="blocked";await session.commit()
    async with client() as c:
        all_rows=(await c.get('/api/v1/assets',headers=curator)).json()['data']
        assert len(all_rows)==5
        published=(await c.get('/api/v1/assets',params={'published_only':True},headers=curator)).json()['data']
        assert {row['asset_id'] for row in published}=={allowed.asset_id}
        assert published[0]['issue_no']==active.issue_no


async def test_readable_unit_count_matches_reader_visibility_and_deduplicates_sources(session):
    from unittest.mock import AsyncMock
    from app.services.assets.catalog import readable_version_unit_counts

    employee = await user(session, "R1", clearance="internal")
    curator = await user(session, "R3")
    asset, version, document, run = await package(session, state="current")
    node = (await session.execute(select(ContentNode).where(ContentNode.parse_run_id == run.parse_run_id))).scalar_one()
    visible = RetrievalUnit(version_id=version.version_id, unit_type="clause", title="可见正文",
        text="第一条 可见正文。", content_hash="1"*64, status="verified", secret_level="internal")
    hidden_unit = RetrievalUnit(version_id=version.version_id, unit_type="clause", title="受限单元",
        text="单位级密级内容。", content_hash="2"*64, status="verified", secret_level="confidential")
    candidate = RetrievalUnit(version_id=version.version_id, unit_type="clause", title="未校验内容",
        text="未校验内容。", content_hash="3"*64, status="candidate", secret_level="internal")
    session.add_all([visible, hidden_unit, candidate]); await session.flush()
    for unit in (visible, hidden_unit, candidate):
        session.add(RetrievalUnitSource(unit_id=unit.unit_id, node_id=node.node_id, sequence=0))
    second_node = ContentNode(document_id=document.document_id, parse_run_id=run.parse_run_id,
        order_path="0002", ordinal=2, node_type="article", text="同一条正文的第二个原文片段。",
        normalized_text="第二片段", source_locator="text:2", content_hash="4"*64, is_citable=True)
    session.add(second_node); await session.flush()
    session.add(RetrievalUnitSource(unit_id=visible.unit_id, node_id=second_node.node_id, sequence=1))

    # The unit itself is internal, but its original document is confidential.
    secret_doc = AssetDocument(filename="受限附件.txt", title="受限附件", object_key="local://secret.txt",
        sha256="5"*64, secret_level="confidential")
    session.add(secret_doc); await session.flush()
    secret_run = DocumentParseRun(document_id=secret_doc.document_id, parser_name="test", is_current=True,
        status="succeeded", source_hash=secret_doc.sha256)
    session.add(secret_run); await session.flush()
    secret_node = ContentNode(document_id=secret_doc.document_id, parse_run_id=secret_run.parse_run_id,
        order_path="0001", ordinal=1, node_type="article", text="附件正文", normalized_text="附件正文",
        source_locator="text:1", content_hash="6"*64, is_citable=True)
    secret_doc_unit = RetrievalUnit(version_id=version.version_id, unit_type="clause", title="受限原件内容",
        text="附件正文", content_hash="7"*64, status="verified", secret_level="internal")
    session.add_all([secret_node, secret_doc_unit, AssetVersionDocument(version_id=version.version_id,
        document_id=secret_doc.document_id, role="normative_annex", mandatory=True, normative=True)])
    await session.flush()
    session.add(RetrievalUnitSource(unit_id=secret_doc_unit.unit_id, node_id=secret_node.node_id, sequence=0))
    await session.commit()
    async with client() as c:
        for headers, expected in ((employee, 1), (curator, 3)):
            listing = (await c.get('/api/v1/assets', headers=headers)).json()['data']
            assert listing[0]['readable_unit_count'] == expected
            reading = (await c.get(f'/api/v1/assets/versions/{version.version_id}/reading', headers=headers)).json()['data']
            assert reading['total'] == expected

    actor = await session.get(User, 'pub_R1')
    permissions = list((await session.execute(select(Permission).where(Permission.role == 'R1'))).scalars())
    original_execute = session.execute
    session.execute = AsyncMock(wraps=original_execute)
    try:
        assert await readable_version_unit_counts(session, actor, permissions) == {version.version_id: 1}
        assert session.execute.await_count == 1  # One aggregate query, regardless of version count.
        assert await readable_version_unit_counts(session, actor, permissions, []) == {}
        assert session.execute.await_count == 1
    finally:
        session.execute = original_execute


async def test_readable_unit_count_excludes_blocked_snapshots_roles_scope_and_dates(session):
    from app.services.assets.catalog import readable_version_unit_counts

    curator = await user(session, "R3", scope="/hq/a/team", clearance="internal", domain="工程")
    versions = []
    for kind in ("allowed", "blocked", "failed", "stale", "reference", "draft", "future", "expired", "other_org", "other_domain"):
        asset, version, document, run = await package(session,
            state="draft" if kind == "draft" else "current",
            scope="/hq/b" if kind == "other_org" else "/hq/a",
            effective=date.today()+timedelta(days=1) if kind == "future" else None,
            expiry=date.today()-timedelta(days=1) if kind == "expired" else None)
        if kind == "blocked": version.ingestion_state = "blocked"
        if kind == "failed": run.status = "requires_ocr"
        if kind == "stale": run.is_current = False
        if kind == "reference":
            link = (await session.execute(select(AssetVersionDocument).where(AssetVersionDocument.version_id == version.version_id))).scalar_one()
            link.role = "reference"; link.normative = False
        if kind == "other_domain": asset.domain = "财务"
        node = (await session.execute(select(ContentNode).where(ContentNode.parse_run_id == run.parse_run_id))).scalar_one()
        unit = RetrievalUnit(version_id=version.version_id, unit_type="clause", title=kind,
            text="带真实原文关联的内容", content_hash="8"*64, status="verified", secret_level="internal")
        session.add(unit); await session.flush()
        session.add(RetrievalUnitSource(unit_id=unit.unit_id, node_id=node.node_id, sequence=0))
        versions.append((kind, version.version_id))
    await session.commit()
    async with client() as c:
        listing = (await c.get('/api/v1/assets', headers=curator)).json()['data']
        counts = {row['version_id']: row['readable_unit_count'] for row in listing}
        assert len(counts) == 8  # Other organization/domain do not leak into the list.
        for kind, version_id in versions:
            if kind in {'other_org', 'other_domain'}:
                assert version_id not in counts
            else:
                assert counts[version_id] == (1 if kind == 'allowed' else 0)
    actor = await session.get(User, 'pub_R3')
    permissions = list((await session.execute(select(Permission).where(Permission.role == 'R3'))).scalars())
    allowed_id = versions[0][1]
    assert await readable_version_unit_counts(session, actor, permissions) == {allowed_id: 1}
    assert await readable_version_unit_counts(session, actor, permissions, [versions[1][1], versions[8][1]]) == {}


async def test_current_reading_scope_pagination_and_download_membership(session, monkeypatch):
    from types import SimpleNamespace
    from app.api.v1 import router_asset
    from app.db.models.asset import RetrievalUnit, RetrievalUnitSource
    employee, curator = await user(session,"R1",clearance="internal"), await user(session,"R3")
    asset, version, document, run = await package(session,state="current")
    node = (await session.execute(select(ContentNode).where(ContentNode.parse_run_id==run.parse_run_id))).scalar_one()
    units = [RetrievalUnit(version_id=version.version_id,unit_type="clause",title=f"第{i}条",text=f"阅读测试正文{i}",content_hash=str(i)*64,status="verified",secret_level="internal") for i in (1,2)]
    hidden = RetrievalUnit(version_id=version.version_id,unit_type="clause",title="受限条款",text="秘密内容",content_hash="9"*64,status="verified",secret_level="confidential")
    session.add_all([*units,hidden]);await session.flush()
    for unit in [*units,hidden]:session.add(RetrievalUnitSource(unit_id=unit.unit_id,node_id=node.node_id,sequence=0))
    link=(await session.execute(select(AssetVersionDocument).where(AssetVersionDocument.version_id==version.version_id))).scalar_one()
    link.normative=False;link.role="form"
    other, other_version, otherdoc, _ = await package(session,state="current")
    await session.commit()
    monkeypatch.setattr(router_asset,"get_object_store",lambda:SimpleNamespace(get_object=lambda key:b"original-source"))
    async with client() as c:
        r=await c.get(f"/api/v1/assets/versions/{version.version_id}/reading",headers=employee,params={"limit":1})
        assert r.status_code==200,r.text
        data=r.json()["data"];assert data["total"]==2 and len(data["clauses"])==1
        assert data["clauses"][0]["clause_id"] in {u.unit_id for u in units}
        assert data["clauses"][0]["file_id"]==asset.asset_id and data["clauses"][0]["source_locator"]=="text:1"
        filtered=(await c.get(f"/api/v1/assets/versions/{version.version_id}/reading",headers=employee,params={"keyword":"正文2"})).json()["data"]
        assert filtered["total"]==1 and filtered["clauses"][0]["content"]=="阅读测试正文2"
        assert (await c.get(f"/api/v1/assets/versions/{version.version_id}/documents/{document.document_id}/download",headers=employee)).content==b"original-source"
        assert (await c.get(f"/api/v1/assets/versions/{version.version_id}/documents/{otherdoc.document_id}/download",headers=employee)).status_code==404
        version.release_state="draft";await session.commit()
        assert (await c.get(f"/api/v1/assets/versions/{version.version_id}/reading",headers=curator)).status_code==404
        assert (await c.get(f"/api/v1/assets/versions/{version.version_id}/documents/{document.document_id}/download",headers=employee)).status_code==404


async def test_replacement_retires_rules_notifies_requester_preserves_case_snapshot(session):
    from copy import deepcopy
    from app.db.models.rule import DecisionRule
    from app.db.models.business_case import BusinessCase
    from app.db.models.push import PushReceipt, PushRecord
    curator, reviewer = await user(session,"R3"), await user(session,"R2")
    await user(session,"R1")
    old_asset, previous, olddoc, oldrun=await package(session,state="current")
    _asset, candidate, _doc, _run=await package(session)
    candidate.asset_id=old_asset.asset_id;candidate.version_label="v2";candidate.supersedes_version_id=previous.version_id
    rule=DecisionRule(rule_key="旧版本规则",scenario="payment",status="current",source_kind="asset",asset_version_id=previous.version_id)
    session.add(rule);await session.flush()
    snapshot={"matched_rule_ids":[rule.rule_id],"evidence":[{"source_kind":"asset","asset_version_id":previous.version_id}],"need_human":False}
    case=BusinessCase(case_no="PUB-HISTORY-1",requester_id="pub_R1",scenario="payment",title="历史事项",status="confirmed",decision_summary="原已确认结论",decision_snapshot=deepcopy(snapshot))
    session.add(case);await session.commit()
    async with client() as c:
        assert (await c.post(f"/api/v1/assets/versions/{candidate.version_id}/submit",headers=curator)).status_code==200
        approved=await c.post(f"/api/v1/assets/versions/{candidate.version_id}/review",headers=reviewer,json={"decision":"approve","note":"已逐项核对替代来源及正文"})
        assert approved.status_code==200,approved.text
    await session.refresh(rule);await session.refresh(previous);await session.refresh(candidate);await session.refresh(case);await session.refresh(oldrun)
    assert rule.status=="retired" and previous.release_state=="replaced" and candidate.release_state=="current"
    assert case.status=="confirmed" and case.decision_snapshot==snapshot and case.decision_summary=="原已确认结论" and oldrun.is_current
    assert candidate.version_metadata["replacement_notice"]["historical_case_count"]==1
    receipt=(await session.execute(select(PushReceipt).where(PushReceipt.user_id=="pub_R1"))).scalar_one()
    push=await session.get(PushRecord,receipt.push_id)
    assert push.status=="sent" and "PUB-HISTORY-1" in push.digest


async def test_maintainer_can_activate_unknown_metadata_without_formal_review(session):
    curator, reviewer, employee = await user(session,"R3"), await user(session,"R2"), await user(session,"R1")
    asset, version, document, run = await package(session)
    asset.owner_org = None; asset.domain = "*"
    version.issue_no = ""; version.effective_date = None
    await session.commit()
    async with client() as c:
        # Stronger formal review remains available, but is no longer the default.
        assert (await c.post(f"/api/v1/assets/versions/{version.version_id}/submit",headers=curator)).status_code==400
        for denied in (employee, reviewer):
            assert (await c.post(f"/api/v1/assets/versions/{version.version_id}/activate",headers=denied,json={"note":"来源可靠"})).status_code==403
        r=await c.post(f"/api/v1/assets/versions/{version.version_id}/activate",headers=curator,json={"note":"本人确认上传原件可靠"})
        assert r.status_code==200,r.text
        preview=(await c.get(f"/api/v1/assets/{asset.asset_id}",headers=employee)).json()["data"]["versions"][0]
        assert preview["authority_verified"] and preview["source_verification"]=="maintainer"
        assert set(preview["authority_gaps"])=={"issue_no","effective_date","owner_org","domain"}
        assert preview["source_confirmation"] is None and preview["reviewed_at"] is None
        management=(await c.get(f"/api/v1/assets/{asset.asset_id}",headers=curator)).json()["data"]["versions"][0]
        assert management["source_confirmation"]["actor_id"]=="pub_R3"
        assert management["source_confirmation"]["version_id"]==version.version_id
        assert management["source_confirmation"]["manifest_fingerprint"]==management["activation_gate"]["manifest_fingerprint"]
        # Repeating a personal declaration never fabricates an R2 decision.
        assert (await c.post(f"/api/v1/assets/versions/{version.version_id}/activate",headers=curator,json={"note":"本人再次确认原件可靠"})).status_code==200
        revision=(await c.post(f"/api/v1/assets/versions/{version.version_id}/revision",headers=curator,json={"version_label":"v2"})).json()["data"]["version_id"]
    await session.refresh(version);await session.refresh(run)
    new_version=await session.get(AssetVersion,revision)
    assert version.release_state=="current" and version.issue_no=="" and version.effective_date is None
    assert version.reviewed_by is None and run.is_current
    assert "source_confirmation" not in new_version.version_metadata
    actions=(await session.execute(select(AuditLog.action).where(AuditLog.target_id==version.version_id))).scalars().all()
    assert actions.count("asset.source_confirmation")==2 and "asset.review" not in actions


async def test_personal_confirmation_never_bypasses_bad_originals_or_scope(session):
    curator=await user(session,"R3",scope="/hq/a",clearance="internal")
    bad=[]
    for status,citable in [("requires_ocr",True),("failed",True),("needs_review",True),("succeeded",False)]:
        _a,v,_d,_r=await package(session,scope="/hq/a",parse_status=status,citable=citable)
        bad.append(v)
    _a,outside,_d,_r=await package(session,scope="/hq/ab")
    _a,secret,_d,_r=await package(session,scope="/hq/a",secret="confidential")
    _a,future,_d,_r=await package(session,scope="/hq/a",effective=date.today()+timedelta(days=1))
    _a,expired,_d,_r=await package(session,scope="/hq/a",expiry=date.today()-timedelta(days=1))
    async with client() as c:
        for v in [*bad,future,expired]:
            r=await c.post(f"/api/v1/assets/versions/{v.version_id}/activate",headers=curator,json={"note":"来源可靠"})
            assert r.status_code==400,r.text
        for v in [outside,secret]:
            assert (await c.post(f"/api/v1/assets/versions/{v.version_id}/activate",headers=curator,json={"note":"来源可靠"})).status_code==404
    for v in [*bad,outside,secret,future,expired]:
        await session.refresh(v)
        assert v.release_state=="draft" and "source_confirmation" not in (v.version_metadata or {})


async def test_confirmation_identity_and_draft_changes_invalidate_attestation(session):
    from app.services.assets.publication import publication_report, source_verification, stamp_source_confirmation
    curator=await user(session,"R3")
    asset,version,document,run=await package(session)
    actor=await session.get(User,"pub_R3")
    permissions=(await session.execute(select(Permission).where(Permission.role=="R3"))).scalars().all()
    report=await publication_report(session,version,asset,actor,permissions,require_authority=False)
    stamp_source_confirmation(version,report,actor,"本人确认原件可靠")
    version.issue_no="";version.effective_date=None;asset.owner_org=None;asset.domain="*"
    await session.commit()
    assert source_verification(asset,version,report=report)=="maintainer"
    document.sha256="c"*64;await session.commit()
    changed=await publication_report(session,version,asset,actor,permissions,require_authority=False)
    assert source_verification(asset,version,report=changed)=="unconfirmed"
    document.sha256="a"*64;await session.commit()
    async with client() as c:
        updated=await c.patch(f"/api/v1/assets/versions/{version.version_id}/metadata",headers=curator,json={"issuer":"来源机构补充","evidence_note":"依据原件首页"})
        assert updated.status_code==200,updated.text
    await session.refresh(version)
    assert "source_confirmation" not in version.version_metadata
    report=await publication_report(session,version,asset,actor,permissions,require_authority=False)
    stamp_source_confirmation(version,report,actor,"本人重新核对")
    await session.commit()
    async with client() as c:
        changed=await c.patch(f"/api/v1/assets/versions/{version.version_id}/documents/{document.document_id}/role",headers=curator,json={"role":"reference","mandatory":True,"normative":False,"evidence_note":"按原件核对用途"})
        assert changed.status_code==200,changed.text
    await session.refresh(version)
    assert "source_confirmation" not in version.version_metadata


async def test_batch_personal_confirmation_only_changes_requested_visible_versions(session):
    curator=await user(session,"R3")
    _a,first,_d,_r=await package(session,state="current")
    _a,second,_d,_r=await package(session,state="pending_review")
    _a,unselected,_d,_r=await package(session,state="current")
    first.issue_no=second.issue_no="";first.effective_date=second.effective_date=None
    await session.commit()
    async with client() as c:
        r=await c.post('/api/v1/assets/source-confirmations',headers=curator,json={"version_ids":[first.version_id,second.version_id,first.version_id],"note":"本人确认当前所选资料可靠"})
        assert r.status_code==200,r.text
        assert r.json()["data"]["count"]==2
    for v in [first,second]:
        await session.refresh(v)
        assert v.release_state=="current" and v.version_metadata["source_confirmation"]["kind"]=="maintainer"
    await session.refresh(unselected)
    assert "source_confirmation" not in (unselected.version_metadata or {})


async def test_manifest_binds_hidden_auxiliary_file_without_disclosing_it(session):
    curator=await user(session,"R3",clearance="internal")
    asset,version,_document,_run=await package(session,state="current")
    asset.owner_org=None;asset.domain="*";version.issue_no="";version.effective_date=None
    hidden=AssetDocument(filename="仅高密级可见附件.txt",title="受限辅助原件",object_key="local://hidden.txt",sha256="d"*64,
                         mime="text/plain",size_bytes=30,secret_level="confidential")
    session.add(hidden);await session.flush()
    session.add(AssetVersionDocument(version_id=version.version_id,document_id=hidden.document_id,role="raw_asset",sort_order=0,mandatory=False,normative=False))
    await session.commit()
    async with client() as c:
        confirmed=await c.post(f"/api/v1/assets/versions/{version.version_id}/activate",headers=curator,json={"note":"本人确认权限内正文可用"})
        assert confirmed.status_code==200,confirmed.text
        details=await c.get(f"/api/v1/assets/{asset.asset_id}",headers=curator)
        assert details.json()["data"]["versions"][0]["source_verification"]=="maintainer"
        assert hidden.filename not in details.text and hidden.document_id not in details.text
        hidden.sha256="e"*64;await session.commit()
        details=await c.get(f"/api/v1/assets/{asset.asset_id}",headers=curator)
        assert details.json()["data"]["versions"][0]["source_verification"]=="unconfirmed"
