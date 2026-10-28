"""Regression coverage for human-readable regulation clause ordering."""
from __future__ import annotations

from types import SimpleNamespace

import httpx

from app.core.security import hash_password
from app.db.models.clause import Clause
from app.db.models.permission import Permission
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.main import app
from app.services.auth.auth_service import issue_token
from app.utils.clause_order import chinese_number, sort_clauses


def _clause(no: str, locator: str | None = None):
    return SimpleNamespace(clause_no=no, source_locator=locator, source_page=None)


def test_chinese_number_supports_article_numbers():
    assert chinese_number("二") == 2
    assert chinese_number("十二") == 12
    assert chinese_number("二十一") == 21
    assert chinese_number("一百零二") == 102
    assert chinese_number("202") == 202


def test_clauses_use_natural_chinese_article_order():
    clauses = [_clause(no) for no in ["第二条", "第十四条", "第十九条", "第十二条", "第六条", "第一条", "第二十条"]]
    assert [item.clause_no for item in sort_clauses(clauses)] == [
        "第一条", "第二条", "第六条", "第十二条", "第十四条", "第十九条", "第二十条",
    ]


def test_explicit_source_locator_preserves_original_document_order():
    clauses = [_clause("附件一", "unit:3"), _clause("正文", "unit:1"), _clause("说明", "unit:2")]
    assert [item.clause_no for item in sort_clauses(clauses)] == ["正文", "说明", "附件一"]


async def test_clause_list_and_preview_return_natural_order(session):
    user = User(
        user_id="u_clause_order", username="u_clause_order",
        hashed_password=hash_password("Zhonggang@123"), role="R4", secret_clearance="internal",
    )
    regulation = RegulationFile(
        file_id="file_clause_order", title="条款排序制度", status="current",
        org_path="/", secret_level="internal",
    )
    session.add_all([
        user,
        Permission(role="R4", org_scope="/", secret_level="internal", domain="*"),
        regulation,
    ])
    await session.flush()
    session.add_all([
        Clause(clause_id="order_14", file_id=regulation.file_id, clause_no="第十四条", content="十四"),
        Clause(clause_id="order_2", file_id=regulation.file_id, clause_no="第二条", content="二"),
        Clause(clause_id="order_12", file_id=regulation.file_id, clause_no="第十二条", content="十二"),
        Clause(clause_id="order_1", file_id=regulation.file_id, clause_no="第一条", content="一"),
    ])
    await session.commit()

    headers = {"Authorization": f"Bearer {issue_token(user)}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        clause_list = await client.get(f"/api/v1/regulations/{regulation.file_id}/clauses", headers=headers)
        preview = await client.get(f"/api/v1/regulations/{regulation.file_id}/preview", headers=headers)

    expected = ["第一条", "第二条", "第十二条", "第十四条"]
    assert [row["clause_no"] for row in clause_list.json()["data"]] == expected
    assert [row["clause_no"] for row in preview.json()["data"]["clauses"]] == expected
