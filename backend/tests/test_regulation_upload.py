"""Upload endpoint tests (software-bugfix-upload-500).

Covers the ``POST /api/v1/regulations/upload`` ingestion path:
  * R3/R4 happy-path upload for .txt / .docx / text-layer .pdf
  * blank/scanned PDF rejection before object storage and ingestion
  * error paths that must yield a clean 400 (not an unhandled 500)
  * role gating (R1 -> 403, no token -> 401)
  * missing file -> 422

Run with: pytest tests/test_regulation_upload.py -v
"""
from __future__ import annotations

import io
import zipfile

import httpx
import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.db.models.clause import Clause
from app.db.models.ingestion import IngestionJob
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.main import app
from app.db.models.permission import Permission
from app.db.models.org import OrgUnit
from app.services.rag.retriever import RetrieverService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_r_role(session, username, password, role):
    if await session.get(OrgUnit, "org_test_owner") is None:
        session.add(OrgUnit(org_id="org_test_owner", name="测试责任部门", path="/owner"))
    user = User(
        user_id=f"u_{username}",
        username=username,
        hashed_password=hash_password(password),
        role=role,
        secret_clearance="internal",
        is_active=True,
    )
    session.add(user)
    session.add(Permission(role=role, org_scope="/", secret_level="secret", domain="*"))
    await session.commit()
    return user


async def _login(client: httpx.AsyncClient, username: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


async def _upload(client, token, filename, data, content_type="application/octet-stream",
                  title=None, **extra):
    form = {
        "title": title or filename,
        "regulation_code": f"TEST-{filename.upper()}",
        "effective_date": "2026-01-01",
        "domain": "综合",
        "owner_org": "org_test_owner",
        "org_path": "/",
        "secret_level": "internal",
        "version": "v1",
        "lang": "zh",
    }
    form.update(extra)
    return await client.post(
        "/api/v1/regulations/upload",
        data=form,
        files={"file": (filename, data, content_type)},
        headers={"Authorization": f"Bearer {token}"},
    )


def _make_docx_bytes() -> bytes:
    """Build a minimal but valid .docx (Office Open XML) in memory."""
    from docx import Document

    doc = Document()
    doc.add_paragraph("第一条 总则")
    doc.add_paragraph("本办法适用于境外项目管理。")
    doc.add_paragraph("第二条 审批权限")
    doc.add_paragraph("变更款由总部审批。")
    doc.add_paragraph("第三条 附则")
    doc.add_paragraph("本办法自发布之日起施行。")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_docx_via_zip() -> bytes:
    """Fallback minimal docx if python-docx is unavailable."""
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        "<w:p><w:r><w:t>第一条 总则</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>本办法适用于境外项目管理。</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>第二条 审批权限</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>变更款由总部审批。</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_upload_txt_success(session) -> None:
    await _seed_r_role(session, "kb_r3", "Zhonggang@123", "R3")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, "kb_r3", "Zhonggang@123")
        txt = "第一条 总则\n本办法适用于境外项目管理。\n第二条 审批权限\n变更款由总部审批。".encode("utf-8")
        resp = await _upload(client, token, "regulation.txt", txt, "text/plain", title="测试制度txt")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["file_id"]
    assert data["status"] == "pending_review"
    assert data["clause_count"] >= 1


async def test_upload_docx_success(session) -> None:
    await _seed_r_role(session, "kb_r3b", "Zhonggang@123", "R3")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, "kb_r3b", "Zhonggang@123")
        docx = _make_docx_bytes()
        resp = await _upload(client, token, "regulation.docx", docx,
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                       title="测试制度docx")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["clause_count"] >= 1


async def test_upload_pdf_success(session) -> None:
    await _seed_r_role(session, "kb_r3c", "Zhonggang@123", "R3")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, "kb_r3c", "Zhonggang@123")
        from reportlab.pdfgen import canvas
        _buf = io.BytesIO()
        pdf_canvas = canvas.Canvas(_buf)
        pdf_canvas.drawString(72, 760, "Article 1 This machine-readable policy applies to overseas projects.")
        pdf_canvas.save()
        pdf = _buf.getvalue()
        resp = await _upload(client, token, "regulation.pdf", pdf, "application/pdf", title="测试制度pdf")
    assert resp.status_code == 200, resp.text
    assert resp.json()["code"] == 0


async def test_upload_scanned_pdf_without_text_layer_is_rejected(session) -> None:
    await _seed_r_role(session, "kb_scan_guard", "Zhonggang@123", "R3")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, "kb_scan_guard", "Zhonggang@123")
        from pypdf import PdfWriter
        buffer = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.write(buffer)
        resp = await _upload(
            client, token, "scan.pdf", buffer.getvalue(), "application/pdf", title="扫描制度"
        )
    assert resp.status_code == 400, resp.text
    assert "先完成OCR" in resp.json()["message"]


async def test_upload_old_doc_rejected_with_400(session) -> None:
    await _seed_r_role(session, "kb_r3d", "Zhonggang@123", "R3")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, "kb_r3d", "Zhonggang@123")
        doc_bytes = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 fake ole content not a real doc"
        resp = await _upload(client, token, "old.doc", doc_bytes, "application/msword", title="旧格式doc")
    # Must be a clean 400, NOT an unhandled 500.
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == 40001


async def test_upload_empty_file_is_rejected(session) -> None:
    await _seed_r_role(session, "kb_r3e", "Zhonggang@123", "R3")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, "kb_r3e", "Zhonggang@123")
        resp = await _upload(client, token, "empty.txt", b"", "text/plain", title="空文件")
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == 40001


async def test_upload_requires_r3_role(session) -> None:
    await _seed_r_role(session, "emp_r1", "Zhonggang@123", "R1")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, "emp_r1", "Zhonggang@123")
        txt = b"first line"
        resp = await _upload(client, token, "no.txt", txt, "text/plain", title="无权限上传")
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == 40301


async def test_upload_without_token_is_401(session) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        txt = b"first line"
        resp = await client.post(
            "/api/v1/regulations/upload",
            data={"title": "x"},
            files={"file": ("no.txt", txt, "text/plain")},
        )
    assert resp.status_code == 401, resp.text
    assert resp.json()["code"] == 40101


async def test_upload_missing_file_is_422(session) -> None:
    await _seed_r_role(session, "kb_r3f", "Zhonggang@123", "R3")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, "kb_r3f", "Zhonggang@123")
        resp = await client.post(
            "/api/v1/regulations/upload",
            data={"title": "nofile"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 422, resp.text


async def test_upload_replacement_publishes_new_version_and_isolates_old_clauses(session) -> None:
    admin = await _seed_r_role(session, "kb_version_admin", "Zhonggang@123", "R3")
    await _seed_r_role(session, "reviewer_r2", "Zhonggang@123", "R2")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, "kb_version_admin", "Zhonggang@123")
        old_response = await _upload(
            client,
            token,
            "policy-v1.txt",
            "第一条 旧版专有要求\n旧版专有要求适用于项目。".encode("utf-8"),
            "text/plain",
            title="项目管理制度",
            regulation_code="ZG-PROJECT-001",
            version="v1.0",
            effective_date="2026-01-01",
        )
        assert old_response.status_code == 200, old_response.text
        old_id = old_response.json()["data"]["file_id"]
        reviewer_token = await _login(client, "reviewer_r2", "Zhonggang@123")
        approved_old = await client.post(
            f"/api/v1/regulations/{old_id}/review",
            json={"approved": True, "note": "首版内容确认"},
            headers={"Authorization": f"Bearer {reviewer_token}"},
        )
        assert approved_old.status_code == 200, approved_old.text

        new_response = await _upload(
            client,
            token,
            "policy-v2.txt",
            "第一条 新版专有要求\n新版专有要求适用于项目。".encode("utf-8"),
            "text/plain",
            title="项目管理制度",
            regulation_code="ZG-PROJECT-001",
            version="v2.0",
            effective_date="2026-08-15",
            replaces_file_id=old_id,
        )
        new_id = new_response.json()["data"]["file_id"]
        approved_new = await client.post(
            f"/api/v1/regulations/{new_id}/review",
            json={"approved": True, "note": "新版内容确认"},
            headers={"Authorization": f"Bearer {reviewer_token}"},
        )

    assert new_response.status_code == 200, new_response.text
    assert approved_new.status_code == 200, approved_new.text
    old = await session.get(RegulationFile, old_id)
    new = await session.get(RegulationFile, new_id)
    old_clauses = list((await session.execute(select(Clause).where(Clause.file_id == old_id))).scalars())
    assert old is not None and old.status == "replaced"
    assert new is not None and new.status == "current"
    assert new.regulation_code == "ZG-PROJECT-001"
    assert str(new.effective_date) == "2026-08-15"
    assert new.replaces_file_id == old_id
    assert old_clauses and {clause.status for clause in old_clauses} == {"isolated"}

    # Retrieval only considers current files/current clauses, so old wording is
    # no longer a possible QA source after the publication transaction.
    permission = Permission(role="R3", org_scope="/", secret_level="secret", domain="*")
    results = await RetrieverService().retrieve(
        session,
        admin,
        [permission],
        "旧版专有要求",
        top_k=10,
        min_score=0.0,
    )
    assert all(result.file.file_id != old_id for result in results)


async def test_upload_existing_code_requires_explicit_replacement(session) -> None:
    await _seed_r_role(session, "kb_version_guard", "Zhonggang@123", "R3")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, "kb_version_guard", "Zhonggang@123")
        first = await _upload(
            client, token, "first.txt", "第一条 内容".encode("utf-8"), "text/plain",
            title="审批制度", regulation_code="ZG-APPROVAL-001", version="v1",
        )
        second = await _upload(
            client, token, "second.txt", "第一条 新内容".encode("utf-8"), "text/plain",
            title="审批制度", regulation_code="ZG-APPROVAL-001", version="v2",
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 400
    assert second.json()["code"] == 40001


async def test_publish_gate_failure_preserves_current_version(session) -> None:
    await _seed_r_role(session, "kb_gate_admin", "Zhonggang@123", "R3")
    await _seed_r_role(session, "gate_reviewer_r2", "Zhonggang@123", "R2")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, "kb_gate_admin", "Zhonggang@123")
        old_response = await _upload(
            client,
            token,
            "gate-v1.txt",
            "第一条 现行要求\n现行要求必须执行。".encode("utf-8"),
            "text/plain",
            title="发布门禁制度",
            regulation_code="ZG-GATE-001",
            version="v1",
        )
        assert old_response.status_code == 200, old_response.text
        old_id = old_response.json()["data"]["file_id"]
        reviewer_token = await _login(client, "gate_reviewer_r2", "Zhonggang@123")
        approved_old = await client.post(
            f"/api/v1/regulations/{old_id}/review",
            json={"approved": True, "note": "首版内容确认"},
            headers={"Authorization": f"Bearer {reviewer_token}"},
        )
        assert approved_old.status_code == 200, approved_old.text
        failed_response = await _upload(
            client,
            token,
            "gate-v2.txt",
            b"",
            "text/plain",
            title="发布门禁制度",
            regulation_code="ZG-GATE-001",
            version="v2",
            replaces_file_id=old_id,
        )

    assert failed_response.status_code == 400, failed_response.text
    assert "文件内容为空" in failed_response.json()["message"]
    old = await session.get(RegulationFile, old_id)
    assert old is not None and old.status == "current"


async def test_r3_can_inspect_and_retry_failed_ingestion_job(session) -> None:
    await _seed_r_role(session, "kb_retry_admin", "Zhonggang@123", "R3")
    await _seed_r_role(session, "retry_employee", "Zhonggang@123", "R1")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _login(client, "kb_retry_admin", "Zhonggang@123")
        upload = await _upload(
            client,
            token,
            "retry-source.txt",
            "第一条 重试测试内容".encode("utf-8"),
            "text/plain",
            title="重试测试制度",
            regulation_code="ZG-RETRY-001",
            version="v1",
        )
        assert upload.status_code == 200, upload.text
        payload = upload.json()["data"]
        job = await session.get(IngestionJob, payload["job_id"])
        regulation = await session.get(RegulationFile, payload["file_id"])
        job.status = "failed"
        job.last_error = "发布评估未通过：测试故障"
        regulation.status = "failed"
        regulation.ingest_error = job.last_error
        regulation.object_key = "local://missing-retry-source.txt"
        await session.commit()
        status = await client.get(f"/api/v1/regulations/{payload['file_id']}/ingestion", headers={"Authorization": f"Bearer {token}"})
        retry = await client.post(
            f"/api/v1/regulations/{payload['file_id']}/ingestion/retry",
            headers={"Authorization": f"Bearer {token}"},
        )
        employee_token = await _login(client, "retry_employee", "Zhonggang@123")
        forbidden = await client.post(
            f"/api/v1/regulations/{payload['file_id']}/ingestion/retry",
            headers={"Authorization": f"Bearer {employee_token}"},
        )

    assert status.status_code == 200
    assert status.json()["data"]["job_id"] == payload["job_id"]
    assert status.json()["data"]["status"] == "failed"
    assert "发布评估未通过" in (status.json()["data"]["last_error"] or "")
    assert retry.status_code == 200
    assert retry.json()["data"]["status"] == "failed"
    assert retry.json()["data"]["job"]["attempt_count"] == 2
    assert forbidden.status_code == 403
