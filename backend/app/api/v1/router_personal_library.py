"""Personal saved documents and reading positions, rechecked under current RBAC.

Preferences are append-only AuditLog events. No business approval or validation
is implied by a bookmark or a reading event.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, exists, func, or_, select, tuple_, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_user_context
from app.core.exceptions import NotFoundError, ok
from app.db.models.asset import AssetVersion, KnowledgeAsset, RetrievalUnit
from app.db.models.audit import AuditLog
from app.db.models.clause import Clause
from app.db.models.feedback import QAFeedback
from app.db.models.qa import QACitation, QASession
from app.db.models.regulation import RegulationFile
from app.db.session import get_db
from app.services.assets.publication import version_filter
from app.services.assets.retrieval_index import eligible_unit_predicates
from app.services.permission.rbac import build_filter
from app.services.rule.evidence import asset_source_statement, legacy_effective_filter

router = APIRouter(prefix="/me/library", tags=["personal-library"])
ADD, REMOVE, READ = "library.favorite.add", "library.favorite.remove", "library.read"
TARGETS = {"regulation": "library.regulation", "asset": "library.asset"}


class Target(BaseModel):
    source_kind: Literal["regulation", "asset"]
    target_id: str = Field(min_length=1, max_length=32)
    asset_version_id: str | None = Field(default=None, max_length=32)


class FavoriteChange(Target):
    saved: bool


class ReadingPosition(Target):
    clause_id: str | None = Field(default=None, max_length=32)


class AnswerFavoriteRemoval(BaseModel):
    session_id: str = Field(min_length=1, max_length=32)


def _current_asset(user, permissions):
    return and_(version_filter(user, permissions), AssetVersion.release_state == "current",
        AssetVersion.ingestion_state == "ready",
        or_(AssetVersion.effective_date.is_(None), AssetVersion.effective_date <= date.today()),
        or_(AssetVersion.expiry_date.is_(None), AssetVersion.expiry_date >= date.today()))


def _visible_event_filter(user, permissions, keyword=""):
    legacy = select(RegulationFile.file_id).where(build_filter(user, permissions), legacy_effective_filter(date.today()))
    assets = select(KnowledgeAsset.asset_id).join(AssetVersion).where(_current_asset(user, permissions))
    if keyword.strip():
        term = keyword.strip().lower()
        legacy = legacy.where(or_(func.lower(RegulationFile.title).contains(term, autoescape=True),
            func.lower(RegulationFile.regulation_code).contains(term, autoescape=True)))
        assets = assets.where(or_(func.lower(KnowledgeAsset.title).contains(term, autoescape=True),
            func.lower(KnowledgeAsset.business_code).contains(term, autoescape=True),
            func.lower(AssetVersion.issue_no).contains(term, autoescape=True)))
    return or_(and_(AuditLog.target_type == TARGETS["regulation"], AuditLog.target_id.in_(legacy)),
        and_(AuditLog.target_type == TARGETS["asset"], AuditLog.target_id.in_(assets)))


def _latest(user_id, actions):
    ranked = select(AuditLog.log_id, func.row_number().over(
        partition_by=(AuditLog.target_type, AuditLog.target_id),
        order_by=(AuditLog.created_at.desc(), AuditLog.log_id.desc())).label("position"))
    ranked = ranked.where(AuditLog.actor_id == user_id, AuditLog.action.in_(actions),
        AuditLog.target_type.in_(list(TARGETS.values()))).subquery()
    return select(AuditLog).join(ranked, ranked.c.log_id == AuditLog.log_id).where(ranked.c.position == 1)


def _details(event):
    try:
        value = json.loads(event.detail or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


async def _resources(db, pairs, user, permissions):
    resources = {}
    legacy_ids = [identifier for kind, identifier in pairs if kind == TARGETS["regulation"]]
    asset_ids = [identifier for kind, identifier in pairs if kind == TARGETS["asset"]]
    if legacy_ids:
        rows = (await db.execute(select(RegulationFile).where(RegulationFile.file_id.in_(legacy_ids),
            build_filter(user, permissions), legacy_effective_filter(date.today())))).scalars()
        for row in rows:
            resources[(TARGETS["regulation"], row.file_id)] = {
                "source_kind": "regulation", "target_id": row.file_id, "title": row.title,
                "version": row.version, "status": row.status, "regulation_code": row.regulation_code,
                "asset_version_id": None,
            }
    if asset_ids:
        rows = (await db.execute(select(KnowledgeAsset, AssetVersion).join(AssetVersion)
            .where(KnowledgeAsset.asset_id.in_(asset_ids), _current_asset(user, permissions))
            .order_by(AssetVersion.created_at.desc(), AssetVersion.version_id.desc()))).all()
        for asset, version in rows:
            resources.setdefault((TARGETS["asset"], asset.asset_id), {
                "source_kind": "asset", "target_id": asset.asset_id, "title": asset.title,
                "version": version.version_label, "status": version.release_state,
                "regulation_code": version.issue_no or asset.business_code, "asset_version_id": version.version_id,
            })
    return resources


async def _locations(db, ids, user, permissions):
    if not ids:
        return {}
    rows = (await db.execute(select(Clause.clause_id, Clause.file_id).join(RegulationFile)
        .where(Clause.clause_id.in_(ids), Clause.status == "current", legacy_effective_filter(date.today()),
            build_filter(user, permissions, Clause.secret_level)))).all()
    locations = {clause_id: ("regulation", file_id, None) for clause_id, file_id in rows}
    rows = (await db.execute(asset_source_statement(user, permissions)
        .with_only_columns(RetrievalUnit.unit_id, KnowledgeAsset.asset_id, AssetVersion.version_id)
        .where(RetrievalUnit.unit_id.in_(ids), *eligible_unit_predicates()))).all()
    locations.update({unit_id: ("asset", asset_id, version_id) for unit_id, asset_id, version_id in rows})
    return locations


async def _cards(db, events, user, permissions):
    pairs = [(event.target_type, event.target_id) for event in events]
    resources = await _resources(db, pairs, user, permissions)
    readings = list((await db.execute(_latest(user.user_id, [READ]).where(
        tuple_(AuditLog.target_type, AuditLog.target_id).in_(pairs or [("none", "none")])))).scalars())
    positions = {(event.target_type, event.target_id): event for event in readings}
    locations = await _locations(db, [_details(event).get("clause_id") for event in readings if _details(event).get("clause_id")], user, permissions)
    cards = []
    for event in events:
        key = (event.target_type, event.target_id)
        resource = resources.get(key)
        if resource is None:
            continue
        reading = positions.get(key)
        position = _details(reading) if reading else {}
        version_changed = bool(reading and (position.get("asset_version_id") != resource["asset_version_id"]
            if resource["source_kind"] == "asset" else position.get("version") != resource["version"]))
        clause_id = position.get("clause_id")
        expected = (resource["source_kind"], resource["target_id"], resource["asset_version_id"])
        resume = clause_id if not version_changed and locations.get(clause_id) == expected else None
        cards.append({**resource, "recorded_at": event.created_at.isoformat(),
            "read_at": reading.created_at.isoformat() if reading else None,
            "resume_clause_id": resume, "version_changed": version_changed})
    return cards


async def _collection(db, user, permissions, actions, limit, offset, keyword=""):
    stmt = _latest(user.user_id, actions).where(_visible_event_filter(user, permissions, keyword))
    if ADD in actions:
        stmt = stmt.where(AuditLog.action == ADD)
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    events = list((await db.execute(stmt.order_by(AuditLog.created_at.desc(), AuditLog.log_id.desc())
        .offset(offset).limit(limit))).scalars())
    return {"items": await _cards(db, events, user, permissions), "total": total, "offset": offset, "limit": limit}


@router.get("/favorites")
async def favorites(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    q: str = Query("", max_length=200),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    return ok(await _collection(db, *ctx, [ADD, REMOVE], limit, offset, q))


@router.get("/recent")
async def recent(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    q: str = Query("", max_length=200),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    return ok(await _collection(db, *ctx, [READ], limit, offset, q))


@router.get("/state")
async def state(source_kind: Literal["regulation", "asset"], target_id: str = Query(min_length=1, max_length=32),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    user, permissions = ctx
    pair = (TARGETS[source_kind], target_id)
    if not await _resources(db, [pair], user, permissions):
        raise NotFoundError("资料不存在或当前不可读")
    event = (await db.execute(_latest(user.user_id, [ADD, REMOVE]).where(
        AuditLog.target_type == pair[0], AuditLog.target_id == target_id))).scalar_one_or_none()
    reading = (await db.execute(_latest(user.user_id, [READ]).where(
        AuditLog.target_type == pair[0], AuditLog.target_id == target_id))).scalar_one_or_none()
    cards = await _cards(db, [reading], user, permissions) if reading else []
    return ok({"saved": bool(event and event.action == ADD), "reading": cards[0] if cards else None})


async def _append(db, user, body, action, resource=None):
    details = {"asset_version_id": resource.get("asset_version_id") if resource else body.asset_version_id,
        "version": resource.get("version") if resource else None}
    if isinstance(body, ReadingPosition):
        details["clause_id"] = body.clause_id
    db.add(AuditLog(actor_id=user.user_id, action=action, target_type=TARGETS[body.source_kind],
        target_id=body.target_id, detail=json.dumps(details), created_at=datetime.now(timezone.utc)))
    await db.commit()


@router.post("/favorite")
async def set_favorite(body: FavoriteChange, ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    user, permissions = ctx
    pair = (TARGETS[body.source_kind], body.target_id)
    resource = (await _resources(db, [pair], user, permissions)).get(pair)
    previous = (await db.execute(_latest(user.user_id, [ADD, REMOVE]).where(
        AuditLog.target_type == pair[0], AuditLog.target_id == pair[1]))).scalar_one_or_none()
    if body.saved and resource is None:
        raise NotFoundError("资料不存在或当前不可读")
    if bool(previous and previous.action == ADD) != body.saved:
        await _append(db, user, body, ADD if body.saved else REMOVE, resource)
    return ok({"saved": body.saved})


@router.post("/reading")
async def remember_reading(body: ReadingPosition, ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    user, permissions = ctx
    pair = (TARGETS[body.source_kind], body.target_id)
    resource = (await _resources(db, [pair], user, permissions)).get(pair)
    if resource is None or (body.source_kind == "asset" and body.asset_version_id != resource["asset_version_id"]):
        raise NotFoundError("资料不存在或当前不可读")
    if body.clause_id:
        locations = await _locations(db, [body.clause_id], user, permissions)
        if locations.get(body.clause_id) != (body.source_kind, body.target_id, resource["asset_version_id"]):
            raise NotFoundError("阅读位置不存在或当前不可读")
    previous = (await db.execute(_latest(user.user_id, [READ]).where(
        AuditLog.target_type == pair[0], AuditLog.target_id == pair[1]))).scalar_one_or_none()
    previous_at = previous.created_at.replace(tzinfo=timezone.utc) if previous else None
    same = previous and _details(previous) == {"asset_version_id": resource["asset_version_id"],
        "version": resource["version"], "clause_id": body.clause_id}
    if not (same and (datetime.now(timezone.utc) - previous_at).total_seconds() < 10):
        await _append(db, user, body, READ, resource)
    return ok({"recorded": True})


@router.get("/answer-favorites")
async def answer_favorites(limit: int = Query(15, ge=1, le=100), offset: int = Query(0, ge=0),
    q: str = Query("", max_length=200),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    user, permissions = ctx
    legacy = select(Clause.clause_id).join(RegulationFile).where(Clause.status == "current",
        legacy_effective_filter(date.today()), build_filter(user, permissions, Clause.secret_level))
    units = asset_source_statement(user, permissions).with_only_columns(RetrievalUnit.unit_id).where(*eligible_unit_predicates())
    hidden = exists(select(QACitation.cite_id).where(QACitation.session_id == QASession.session_id,
        QACitation.clause_id.not_in(union(legacy, units))))
    stmt = select(QASession, func.max(QAFeedback.created_at).label("saved_at")).join(QAFeedback).where(
        QASession.user_id == user.user_id, QASession.is_evaluation.is_(False),
        func.length(func.trim(QASession.answer_interpret)) > 0, QAFeedback.user_id == user.user_id,
        QAFeedback.type == "favorite", ~hidden).group_by(QASession.session_id)
    if q.strip():
        term = q.strip().lower()
        stmt = stmt.where(or_(func.lower(QASession.question).contains(term, autoescape=True),
            func.lower(QASession.answer_interpret).contains(term, autoescape=True)))
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    rows = (await db.execute(stmt.order_by(func.max(QAFeedback.created_at).desc(), QASession.session_id)
        .offset(offset).limit(limit))).all()
    return ok({"items": [{"session_id": row.session_id, "question": row.question[:240],
        "answer_excerpt": row.answer_interpret[:180], "saved_at": saved_at.isoformat()}
        for row, saved_at in rows], "total": total, "offset": offset, "limit": limit})


@router.post("/answer-favorites/remove")
async def remove_answer_favorite(body: AnswerFavoriteRemoval, ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    user, _permissions = ctx
    session = await db.get(QASession, body.session_id)
    if session is None or session.user_id != user.user_id:
        raise NotFoundError("咨询记录不存在")
    await db.execute(delete(QAFeedback).where(QAFeedback.session_id == body.session_id,
        QAFeedback.user_id == user.user_id, QAFeedback.type == "favorite"))
    db.add(AuditLog(actor_id=user.user_id, action="qa.favorite.remove", target_type="qa_session", target_id=body.session_id))
    await db.commit()
    return ok({"saved": False})
