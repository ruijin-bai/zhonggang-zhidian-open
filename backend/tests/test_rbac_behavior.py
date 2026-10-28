"""RBAC row-level filtering behaviour (architecture §7.5).

The string-fragment checks in ``test_rbac.py`` only assert the SQL contains
``LIKE``/``IN``. This file verifies the predicate actually filters rows:
a higher secret level must be invisible to a lower-clearance user, and a
domain-scoped permission must hide out-of-domain files.
"""
from __future__ import annotations

from sqlalchemy import select

from app.db.models.clause import Clause
from app.db.models.permission import Permission
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.services.permission.rbac import build_filter


async def test_rbac_excludes_higher_secret_level(session):
    conf = RegulationFile(
        title="机密文件", owner_org=None, org_path="/hq",
        secret_level="confidential", domain="*", status="current",
    )
    inter = RegulationFile(
        title="内部文件", owner_org=None, org_path="/hq",
        secret_level="internal", domain="*", status="current",
    )
    session.add_all([conf, inter])
    await session.flush()

    user = User(user_id="u_r1", role="R1", secret_clearance="internal")
    perm = Permission(role="R1", org_scope="/hq", secret_level="internal", domain="*")

    rows = (await session.execute(select(RegulationFile).where(build_filter(user, [perm])))).scalars().all()
    titles = {r.title for r in rows}
    assert "内部文件" in titles
    assert "机密文件" not in titles  # confidential > internal clearance → hidden


async def test_rbac_domain_restriction(session):
    f_a = RegulationFile(
        title="域A制度", owner_org=None, org_path="/", secret_level="public", domain="域A", status="current",
    )
    f_b = RegulationFile(
        title="域B制度", owner_org=None, org_path="/", secret_level="public", domain="域B", status="current",
    )
    session.add_all([f_a, f_b])
    await session.flush()

    user = User(user_id="u_r4", role="R4", secret_clearance="public")
    perm = Permission(role="R4", org_scope="/", secret_level="public", domain="域A")

    rows = (await session.execute(select(RegulationFile).where(build_filter(user, [perm])))).scalars().all()
    titles = {r.title for r in rows}
    assert "域A制度" in titles
    assert "域B制度" not in titles  # out-of-domain → hidden


async def test_rbac_empty_permissions_yield_no_rows(session):
    f = RegulationFile(
        title="任一文件", owner_org=None, org_path="/", secret_level="public", domain="*", status="current",
    )
    session.add(f)
    await session.flush()
    user = User(user_id="u_x", role="R1", secret_clearance="public")
    rows = (await session.execute(select(RegulationFile).where(build_filter(user, [])))).scalars().all()
    assert rows == []


async def test_rbac_uses_the_lower_of_user_and_role_secret_clearance(session):
    confidential = RegulationFile(
        title="角色可见但个人不可见", owner_org=None, org_path="/",
        secret_level="confidential", domain="*", status="current",
    )
    session.add(confidential)
    await session.flush()

    user = User(user_id="u_personal_internal", role="R1", secret_clearance="internal")
    role_permission = Permission(role="R1", org_scope="/", secret_level="secret", domain="*")
    rows = (await session.execute(
        select(RegulationFile).where(build_filter(user, [role_permission]))
    )).scalars().all()
    assert rows == []


async def test_clause_secret_level_is_enforced_with_the_matching_role_permission(session):
    file = RegulationFile(
        file_id="file_clause_levels", title="内部制度", owner_org=None, org_path="/",
        secret_level="internal", domain="*", status="current",
    )
    session.add(file)
    await session.flush()
    session.add_all([
        Clause(file_id=file.file_id, clause_id="clause_internal", clause_no="第一条", content="内部条款", secret_level="internal"),
        Clause(file_id=file.file_id, clause_id="clause_confidential", clause_no="第二条", content="机密条款", secret_level="confidential"),
    ])
    await session.flush()

    user = User(user_id="u_role_internal", role="R1", secret_clearance="secret")
    role_permission = Permission(role="R1", org_scope="/", secret_level="internal", domain="*")
    rows = (await session.execute(
        select(Clause)
        .join(RegulationFile, Clause.file_id == RegulationFile.file_id)
        .where(build_filter(user, [role_permission], Clause.secret_level))
    )).scalars().all()
    assert [row.clause_id for row in rows] == ["clause_internal"]


async def test_company_wide_regulation_visible_to_nested_scope(session):
    company = RegulationFile(
        title="公司级制度", owner_org=None, org_path="/",
        secret_level="internal", domain="*", status="current",
    )
    overseas_only = RegulationFile(
        title="驻外专用制度", owner_org=None, org_path="/hq/region1/overseas1",
        secret_level="internal", domain="*", status="current",
    )
    session.add_all([company, overseas_only])
    await session.flush()

    # 驻外员工：公司级制度 + 驻外专用制度都应在范围内。
    user = User(user_id="u_overseas", role="R1", secret_clearance="internal")
    perm = Permission(role="R1", org_scope="/hq/region1/overseas1", secret_level="internal", domain="*")
    rows = (await session.execute(select(RegulationFile).where(build_filter(user, [perm])))).scalars().all()
    titles = {r.title for r in rows}
    assert "公司级制度" in titles
    assert "驻外专用制度" in titles

    # 总部员工：能看到公司级制度，但看不到驻外专用制度。
    hq_user = User(user_id="u_hq", role="R1", secret_clearance="internal")
    hq_perm = Permission(role="R1", org_scope="/hq", secret_level="internal", domain="*")
    hq_rows = (await session.execute(select(RegulationFile).where(build_filter(hq_user, [hq_perm])))).scalars().all()
    hq_titles = {r.title for r in hq_rows}
    assert "公司级制度" in hq_titles
    assert "驻外专用制度" not in hq_titles
