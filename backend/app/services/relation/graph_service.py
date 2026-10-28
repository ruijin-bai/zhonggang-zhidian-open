"""Cross-file relation maintenance and graph aggregation (architecture §6 T06)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import RelationType
from app.db.models.relation import Relation
from app.db.models.regulation import RegulationFile
from app.services.permission.rbac import build_filter


async def create_relation(
    session: AsyncSession,
    *,
    from_id: str,
    to_id: str,
    rel_type: str,
    note: str | None = None,
    confirmed_by: str | None = None,
) -> Relation:
    rel = Relation(from_id=from_id, to_id=to_id, rel_type=rel_type, note=note, confirmed_by=confirmed_by)
    session.add(rel)
    await session.flush()
    return rel


async def list_relations(
    session: AsyncSession,
    user,
    permissions,
    file_id: str | None = None,
) -> list[Relation]:
    """Return only relations whose two endpoint regulations are visible.

    A relation's type and note may disclose a hidden regulation's existence, so
    filtering only the graph nodes is insufficient.  The predicate stays in
    SQL for both the list and graph API paths.
    """
    visible_file_ids = select(RegulationFile.file_id).where(build_filter(user, permissions))
    stmt = select(Relation).where(
        Relation.from_id.in_(visible_file_ids),
        Relation.to_id.in_(visible_file_ids),
    )
    if file_id:
        stmt = stmt.where((Relation.from_id == file_id) | (Relation.to_id == file_id))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def build_graph(
    session: AsyncSession,
    user,
    permissions,
    file_id: str | None = None,
) -> dict:
    """Return {nodes, edges} for the relation graph, RBAC-filtered."""
    perm_filter = build_filter(user, permissions)
    stmt = select(RegulationFile).where(perm_filter)
    if file_id:
        stmt = stmt.where(RegulationFile.file_id == file_id)
    files = list((await session.execute(stmt)).scalars().all())
    file_ids = {f.file_id for f in files}

    rels = await list_relations(session, user, permissions)
    edges = [
        {
            "rel_id": r.rel_id,
            "from": r.from_id,
            "to": r.to_id,
            "type": r.rel_type,
            "type_label": RelationType.label(r.rel_type),
            "note": r.note,
            "confirmed_by": r.confirmed_by,
        }
        for r in rels
        if r.from_id in file_ids and r.to_id in file_ids
    ]
    nodes = [
        {
            "id": f.file_id,
            "title": f.title,
            "version": f.version,
            "status": f.status,
            "org_path": f.org_path,
            "secret_level": f.secret_level,
            "domain": f.domain,
        }
        for f in files
    ]
    conflicts = [
        {"from": e["from"], "to": e["to"], "note": e["note"]}
        for e in edges
        if e["type"] == RelationType.CONFLICT.value
    ]
    return {"nodes": nodes, "edges": edges, "conflicts": conflicts}
