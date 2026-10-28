"""Cross-file relation & graph endpoints (T06 / T11)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_user_context, require_roles
from app.core.exceptions import NotFoundError, ok
from app.db.models.relation import Relation
from app.db.session import get_db
from app.schemas.relation import GraphOut, RelationCreate, RelationOut
from app.services.relation.graph_service import build_graph, create_relation, list_relations

router = APIRouter(prefix="/relations", tags=["relations"])


@router.post("", response_model=None)
async def create(
    body: RelationCreate,
    _: object = Depends(require_roles("R3", "R4")),
    db: AsyncSession = Depends(get_db),
):
    rel = await create_relation(
        db, from_id=body.from_id, to_id=body.to_id, rel_type=body.rel_type,
        note=body.note, confirmed_by=body.confirmed_by,
    )
    await db.commit()
    return ok(RelationOut(
        rel_id=rel.rel_id, from_id=rel.from_id, to_id=rel.to_id,
        rel_type=rel.rel_type, note=rel.note, confirmed_by=rel.confirmed_by,
    ).model_dump())


@router.get("", response_model=None)
async def list_all(ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    user, perms = ctx
    rels = await list_relations(db, user, perms)
    return ok(
        [
            RelationOut(
                rel_id=r.rel_id, from_id=r.from_id, to_id=r.to_id,
                rel_type=r.rel_type, note=r.note, confirmed_by=r.confirmed_by,
            ).model_dump()
            for r in rels
        ]
    )


@router.get("/graph", response_model=None)
async def graph(ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    user, perms = ctx
    g = await build_graph(db, user, perms)
    return ok(GraphOut(**g).model_dump())


@router.delete("/{rel_id}", response_model=None)
async def delete(
    rel_id: str,
    _: object = Depends(require_roles("R3", "R4")),
    db: AsyncSession = Depends(get_db),
):
    rel = await db.get(Relation, rel_id)
    if rel is None:
        raise NotFoundError("关系不存在")
    await db.delete(rel)
    await db.flush()
    await db.commit()
    return ok({"rel_id": rel_id})
