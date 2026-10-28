"""Compound-asset V2 management API acceptance tests."""
from __future__ import annotations

import json
import httpx

from app.core.security import hash_password
from app.db.models.asset import (
    AssetDocument,
    AssetVersion,
    AssetVersionDocument,
    ContentNode,
    DocumentParseRun,
    KnowledgeAsset,
)
from app.db.models.permission import Permission
from app.db.models.user import User
from app.main import app


async def _admin_token(client: httpx.AsyncClient, session) -> str:
    session.add(User(
        user_id="asset_api_admin",
        username="asset_api_admin",
        hashed_password=hash_password("AssetApi@123"),
        role="R4",
        secret_clearance="secret",
        is_active=True,
    ))
    session.add(Permission(role="R4", org_scope="/", secret_level="secret", domain="*"))
    await session.commit()
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "asset_api_admin", "password": "AssetApi@123"},
    )
    return response.json()["data"]["access_token"]


async def test_asset_management_read_apis(session):
    asset = KnowledgeAsset(
        asset_type="management_method",
        title="复合资产API样本",
        business_code="ZG-ASSET-001",
        status="active",
    )
    session.add(asset)
    await session.flush()
    version = AssetVersion(
        asset_id=asset.asset_id,
        version_label="v1",
        release_state="current",
        ingestion_state="ready",
    )
    document = AssetDocument(
        filename="正文.docx",
        title="正文",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        object_key="local://asset-api.docx",
        sha256="c" * 64,
        size_bytes=123,
        parse_disposition="structured",
    )
    session.add_all([version, document])
    await session.flush()
    session.add(AssetVersionDocument(
        version_id=version.version_id,
        document_id=document.document_id,
        role="normative_body",
        mandatory=True,
        normative=True,
    ))
    run = DocumentParseRun(
        document_id=document.document_id,
        parser_name="docx_ooxml_ast",
        parser_version="1",
        status="succeeded",
        is_current=True,
        source_hash=document.sha256,
        config_hash="d" * 64,
        quality_report={"node_count": 1, "citable_count": 1},
    )
    session.add(run)
    await session.flush()
    node = ContentNode(
        parse_run_id=run.parse_run_id,
        document_id=document.document_id,
        node_type="article",
        order_path="000001",
        ordinal=1,
        label="第一条",
        title="",
        text="本办法适用于测试。",
        normalized_text="本办法适用于测试。",
        source_locator="word:/document/body/p[1]",
        content_hash="e" * 64,
        is_citable=True,
    )
    session.add(node)
    await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _admin_token(client, session)
        headers = {"Authorization": f"Bearer {token}"}
        taxonomy = await client.get("/api/v1/assets/taxonomy", headers=headers)
        summary = await client.get("/api/v1/assets/summary", headers=headers)
        listing = await client.get("/api/v1/assets", headers=headers)
        detail = await client.get(f"/api/v1/assets/{asset.asset_id}", headers=headers)
        tree = await client.get(
            f"/api/v1/assets/documents/{document.document_id}/tree", headers=headers
        )
        created = await client.post(
            "/api/v1/assets",
            headers=headers,
            data={
                "title": "多文件资产包",
                "asset_type": "regulation",
                "business_code": "ZG-PACK-001",
                "version_label": "v1",
                "manifest_json": json.dumps([
                    {"role": "normative_body", "mandatory": True, "normative": True},
                    {"role": "normative_annex", "mandatory": True, "normative": True},
                ]),
            },
            files=[
                ("files", ("正文.txt", "第一条 正文要求".encode(), "text/plain")),
                ("files", ("附件.txt", "附件一 申报要求".encode(), "text/plain")),
            ],
        )

    assert taxonomy.status_code == 200
    assert any(item["value"] == "template_package" for item in taxonomy.json()["data"]["asset_types"])
    assert summary.json()["data"]["parse_states"] == {"succeeded": 1}
    assert listing.json()["data"][0]["document_count"] == 1
    assert detail.json()["data"]["versions"][0]["documents"][0]["role"] == "normative_body"
    assert tree.json()["data"]["nodes"][0]["source_locator"] == "word:/document/body/p[1]"
    assert created.status_code == 200, created.text
    assert len(created.json()["data"]["document_ids"]) == 2


async def test_asset_employee_can_list_only_visible_published_versions(session):
    session.add(User(
        user_id="asset_api_employee",
        username="asset_api_employee",
        hashed_password=hash_password("AssetApi@123"),
        role="R1",
        secret_clearance="internal",
        is_active=True,
    ))
    session.add(Permission(role="R1", org_scope="/", secret_level="internal", domain="*"))
    await session.commit()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"username": "asset_api_employee", "password": "AssetApi@123"},
        )
        response = await client.get(
            "/api/v1/assets",
            headers={"Authorization": f"Bearer {login.json()['data']['access_token']}"},
        )
    assert response.status_code == 200
    assert response.json()["data"] == []
