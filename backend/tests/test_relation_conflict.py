"""Relation graph conflict identification tests (T06 / §6).

Covers the RBAC-filtered graph aggregation:
  * A conflict relation between two *visible* files is surfaced in ``conflicts``
    with its note preserved (the "以 X 为准" prompt source).
  * Non-conflict relations are excluded from ``conflicts``.
  * Files outside the caller's clearance are dropped from nodes, which also
    removes any edges/conflicts that would otherwise leak across the boundary.
"""
from __future__ import annotations

from app.db.models.permission import Permission
from app.db.models.relation import Relation
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.services.relation.graph_service import build_graph


async def test_build_graph_reports_conflicts(session):
    fa = RegulationFile(file_id="f_a", title="办法A", org_path="/", secret_level="internal", domain="*", status="current")
    fb = RegulationFile(file_id="f_b", title="办法B", org_path="/", secret_level="internal", domain="*", status="current")
    session.add_all([fa, fb])
    await session.flush()
    session.add(Relation(from_id="f_a", to_id="f_b", rel_type="conflict", note="以办法A为准"))
    session.add(Relation(from_id="f_a", to_id="f_b", rel_type="subordinate", note="从属"))
    await session.commit()

    user = User(user_id="u_g", username="u_g", role="R4", secret_clearance="secret")
    perms = [Permission(role="R4", org_scope="/", secret_level="secret", domain="*")]
    graph = await build_graph(session, user, perms)

    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) == 2

    conflicts = graph["conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["from"] == "f_a"
    assert conflicts[0]["to"] == "f_b"
    assert conflicts[0]["note"] == "以办法A为准"


async def test_build_graph_hides_unauthorized_files(session):
    f_pub = RegulationFile(file_id="f_pub", title="公开办法", org_path="/", secret_level="public", domain="*", status="current")
    f_sec = RegulationFile(file_id="f_sec", title="绝密办法", org_path="/hq", secret_level="secret", domain="*", status="current")
    session.add_all([f_pub, f_sec])
    await session.flush()
    session.add(Relation(from_id="f_pub", to_id="f_sec", rel_type="conflict", note="冲突"))
    await session.commit()

    # R1 limited to internal + "/" cannot see the secret file at /hq.
    user = User(user_id="u_l", username="u_l", role="R1", secret_clearance="internal")
    perms = [Permission(role="R1", org_scope="/", secret_level="internal", domain="*")]
    graph = await build_graph(session, user, perms)

    visible_ids = {n["id"] for n in graph["nodes"]}
    assert "f_pub" in visible_ids
    assert "f_sec" not in visible_ids
    # Edge requires BOTH endpoints visible, so the conflict is filtered out.
    assert graph["conflicts"] == []
