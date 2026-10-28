"""Release review workflow: unpublished candidates never leak to employees."""
from __future__ import annotations

import httpx
from datetime import date

from app.core.security import hash_password
from app.db.models.clause import Clause
from app.db.models.permission import Permission
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.db.models.org import OrgUnit
from app.main import app
from app.services.auth.auth_service import issue_token


async def _seed(session, user_id: str, role: str) -> User:
    user = User(
        user_id=user_id,
        username=user_id,
        hashed_password=hash_password("Zhonggang@123"),
        role=role,
        secret_clearance="secret",
    )
    session.add_all([user, Permission(role=role, org_scope="/", secret_level="secret", domain="*")])
    await session.flush()
    return user


async def test_review_is_required_before_employee_can_read_candidate(session):
    employee = await _seed(session, "u_review_employee", "R1")
    reviewer = await _seed(session, "u_review_reviewer", "R2")
    curator = await _seed(session, "u_review_curator", "R3")
    session.add(OrgUnit(org_id="org_review_owner", name="制度责任部门", parent_id=None, path="/owner"))
    await session.flush()
    candidate = RegulationFile(
        file_id="file_review_candidate",
        regulation_code="ZG-REVIEW-001",
        title="待审核项目管理制度",
        version="v1",
        status="pending_review",
        org_path="/",
        secret_level="internal",
        owner_org="org_review_owner",
        effective_date=date.today(),
        domain="工程",
    )
    session.add(candidate)
    session.add(
        Clause(
            clause_id="clause_review_candidate",
            file_id=candidate.file_id,
            clause_no="第一条",
            content="待审核条款不得在发布前向员工展示。",
            secret_level="internal",
            status="current",
        )
    )
    await session.commit()

    employee_headers = {"Authorization": f"Bearer {issue_token(employee)}"}
    reviewer_headers = {"Authorization": f"Bearer {issue_token(reviewer)}"}
    curator_headers = {"Authorization": f"Bearer {issue_token(curator)}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        employee_list = await client.get("/api/v1/regulations", headers=employee_headers)
        employee_detail = await client.get(f"/api/v1/regulations/{candidate.file_id}", headers=employee_headers)
        employee_preview = await client.get(f"/api/v1/regulations/{candidate.file_id}/preview", headers=employee_headers)
        review_list = await client.get("/api/v1/regulations/reviews/pending", headers=reviewer_headers)
        review_preview = await client.get(
            f"/api/v1/regulations/reviews/{candidate.file_id}/preview", headers=reviewer_headers
        )
        forbidden_approve = await client.post(
            f"/api/v1/regulations/{candidate.file_id}/review",
            json={"approved": True, "note": "越权"},
            headers=curator_headers,
        )
        missing_reason = await client.post(
            f"/api/v1/regulations/{candidate.file_id}/review",
            json={"approved": False, "note": ""},
            headers=reviewer_headers,
        )
        rejected = await client.post(
            f"/api/v1/regulations/{candidate.file_id}/review",
            json={"approved": False, "note": "请补充签发依据"},
            headers=reviewer_headers,
        )
        resubmitted = await client.post(
            f"/api/v1/regulations/{candidate.file_id}/review/resubmit",
            headers=curator_headers,
        )
        approved = await client.post(
            f"/api/v1/regulations/{candidate.file_id}/review",
            json={"approved": True, "note": "签发依据已核对"},
            headers=reviewer_headers,
        )
        employee_after_publish = await client.get(f"/api/v1/regulations/{candidate.file_id}", headers=employee_headers)

    assert employee_list.status_code == 200
    assert employee_list.json()["data"] == []
    assert employee_detail.status_code == 404
    assert employee_preview.status_code == 404
    assert review_list.status_code == 200
    assert review_list.json()["data"][0]["file_id"] == candidate.file_id
    assert review_preview.status_code == 200
    assert review_preview.json()["data"]["clauses"][0]["clause_id"] == "clause_review_candidate"
    assert forbidden_approve.status_code == 403
    assert missing_reason.status_code == 400
    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "rejected"
    assert resubmitted.status_code == 200
    assert resubmitted.json()["data"]["status"] == "pending_review"
    assert approved.status_code == 200
    assert approved.json()["data"]["status"] == "current"
    assert employee_after_publish.status_code == 200
    assert employee_after_publish.json()["data"]["review_note"] == "签发依据已核对"
