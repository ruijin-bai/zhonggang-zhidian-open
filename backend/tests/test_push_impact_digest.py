"""Push impact identification & change-digest tests (T13).

Verifies the no-key, sqlite path for:
  * identify_impact — collects scenario tags, visible roles, related files
    (and returns empty-struct gracefully when the file is missing).
  * generate_digest — summarises clause counts / scenarios and injects the
    "以新版或上级制度为准" conflict hint whenever a conflict relation touches the file.
"""
from __future__ import annotations

from app.db.models.clause import Clause
from app.db.models.permission import Permission
from app.db.models.relation import Relation
from app.db.models.regulation import RegulationFile
from app.services.push.digest import generate_digest
from app.services.push.impact import identify_impact


async def _make_file(session, file_id, domain="*", secret_level="internal", org_path="/", version="v2"):
    f = RegulationFile(
        file_id=file_id, title=f"制度{file_id}", org_path=org_path,
        secret_level=secret_level, domain=domain, status="current", version=version,
    )
    session.add(f)
    await session.flush()
    return f


async def test_identify_impact_missing_file_returns_empty(session):
    impact = await identify_impact(session, "no_such_file")
    assert impact == {"scenario_tags": [], "roles": [], "related_files": []}


async def test_identify_impact_collects_tags_and_roles(session):
    await _make_file(session, "file_a", domain="境外项目", secret_level="internal")
    session.add(Clause(
        file_id="file_a", clause_no="第1条", content="境外项目变更款审批。",
        secret_level="internal", scenario_tags=["变更款审批", "审批权限"], status="current",
    ))
    # A permission that can see this file (domain match + secret ok + org prefix).
    session.add(Permission(role="R1", org_scope="/", secret_level="secret", domain="境外项目"))
    await session.commit()

    impact = await identify_impact(session, "file_a")
    assert "变更款审批" in impact["scenario_tags"]
    assert "审批权限" in impact["scenario_tags"]
    assert "R1" in impact["roles"]
    assert impact["related_files"] == []


async def test_generate_digest_includes_scenarios(session):
    await _make_file(session, "file_d")
    session.add(Clause(
        file_id="file_d", clause_no="第3条", content="差旅费报销标准。",
        secret_level="internal", scenario_tags=["差旅费"], status="current",
    ))
    await session.commit()
    digest = await generate_digest(session, "file_d")
    assert "制度《制度file_d》" in digest
    assert "差旅费" in digest
    assert "1 条" in digest


async def test_generate_digest_conflict_hint(session):
    await _make_file(session, "file_x")
    await _make_file(session, "file_y")
    session.add(Relation(
        from_id="file_x", to_id="file_y", rel_type="conflict", note="以新版制度为准",
    ))
    await session.commit()
    digest = await generate_digest(session, "file_x")
    assert "以新版或上级制度为准" in digest
