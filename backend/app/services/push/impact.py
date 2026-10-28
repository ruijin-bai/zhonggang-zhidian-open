"""Impact identification: which scenarios / roles a revised file affects (T13)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import SecretLevel
from app.db.models.clause import Clause
from app.db.models.permission import Permission
from app.db.models.regulation import RegulationFile


async def identify_impact(session: AsyncSession, file_id: str) -> dict:
    file = await session.get(RegulationFile, file_id)
    if file is None:
        return {"scenario_tags": [], "roles": [], "related_files": []}

    result = await session.execute(select(Clause).where(Clause.file_id == file_id))
    clauses = list(result.scalars().all())
    scenario_tags: list[str] = []
    for c in clauses:
        for t in c.scenario_tags or []:
            if t not in scenario_tags:
                scenario_tags.append(t)

    # Roles that may see this file (domain + secret + org prefix).
    perm_result = await session.execute(select(Permission))
    roles: list[str] = []
    for p in perm_result.scalars().all():
        domain_ok = p.domain == "*" or p.domain == file.domain
        secret_ok = SecretLevel.rank(p.secret_level) >= SecretLevel.rank(file.secret_level)
        org_ok = file.org_path.startswith(p.org_scope)
        if domain_ok and secret_ok and org_ok and p.role not in roles:
            roles.append(p.role)

    # Related files via relations.
    from app.db.models.relation import Relation

    rel_res = await session.execute(
        select(Relation).where((Relation.from_id == file_id) | (Relation.to_id == file_id))
    )
    related = {r.to_id if r.from_id == file_id else r.from_id for r in rel_res.scalars().all()}

    return {"scenario_tags": scenario_tags, "roles": roles, "related_files": list(related)}
