"""Competition mainline regression coverage contract and missing high-risk gate."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import httpx

from app.core.security import hash_password
from app.db.models.impact import ChangeImpactItem, ChangeImpactRun
from app.db.models.org import OrgUnit
from app.db.models.permission import Permission
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.main import app
from app.services.auth.auth_service import issue_token

TEST_ROOT = Path(__file__).resolve().parent


def test_competition_regression_manifest_points_to_collected_tests():
    manifest = json.loads((TEST_ROOT / "competition_regression_manifest.json").read_text(encoding="utf-8"))
    assert set(manifest) == {
        "qa_clarification_citation_security", "claim_grounding_numeric", "authority_gate",
        "rule_boundary_currency_path_materials", "version_replacement_rule_retirement_history",
        "high_risk_cannot_close",
    }
    for target in manifest.values():
        filename, function_name = target.split("::", 1)
        tree = ast.parse((TEST_ROOT / filename).read_text(encoding="utf-8"))
        functions = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert function_name in functions, target


async def test_high_risk_impact_cannot_be_confirmed(session):
    reviewer = User(
        user_id="competition_reviewer", username="competition_reviewer",
        hashed_password=hash_password("Password@123"), role="R2", secret_clearance="internal",
    )
    permission = Permission(role="R2", org_scope="/", secret_level="internal", domain="*")
    owner = OrgUnit(org_id="competition_owner", name="制度责任部门", path="/")
    regulation = RegulationFile(
        file_id="competition_v2", regulation_code="ZG-COMP-001", title="境外项目变更办法",
        version="v2", status="current", owner_org=owner.org_id, org_path="/", domain="contract_change",
    )
    run = ChangeImpactRun(impact_id="competition_impact", new_file_id=regulation.file_id, status="draft")
    item = ChangeImpactItem(
        item_id="competition_high_item", impact_id=run.impact_id, item_type="rule_rebuild_required",
        object_type="decision_rule", severity="high", status="pending",
    )
    session.add_all([reviewer, permission, owner, regulation, run, item])
    await session.commit()
    headers = {"Authorization": f"Bearer {issue_token(reviewer)}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/impacts/competition_impact/confirm", json={"note": "尝试直接关闭"}, headers=headers,
        )
    assert response.status_code == 400
    assert "高风险" in response.json()["message"]
