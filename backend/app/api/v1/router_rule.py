"""Governed rule authoring and business review endpoints."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_user_context, require_roles
from app.core.exceptions import BadRequestError, NotFoundError, ok
from app.db.enums import DecisionRuleStatus
from app.db.models.clause import Clause
from app.db.models.governance_task import GovernanceTask
from app.db.models.regulation import RegulationFile
from app.db.models.rule import DecisionRule
from app.db.models.asset import AssetVersion, KnowledgeAsset, RetrievalUnit
from app.db.models.org import OrgUnit
from app.db.session import get_db
from app.schemas.rule import DecisionRuleCreate, DecisionRuleOut, DecisionRuleReviewRequest
from app.services.audit import record_audit
from app.services.permission.rbac import build_filter
from app.services.rule.evaluator import regulation_effective_filter
from app.services.governance import build_rule_candidates
from app.services.governance_state import is_authority_verified
from app.services.rule.evidence import load_rule_sources, source_for_create, asset_source_statement, normalise_asset_source, asset_authority_gaps
from app.utils.clause_order import sort_clauses

router = APIRouter(prefix="/rules", tags=["rules"])


async def _validate_activation_scope(db, scope, permissions):
    if scope != "/" and not await db.scalar(select(OrgUnit.org_id).where(OrgUnit.path == scope)):
        raise BadRequestError("规则适用组织不存在")
    for permission in permissions:
        own = (permission.org_scope or "").rstrip("/")
        if permission.org_scope == "/" or (own.startswith("/") and (scope == own or scope.startswith(own + "/"))):
            return
    raise BadRequestError("只能启用当前账号组织范围内的规则")

def _out(rule: DecisionRule, clause: Clause, file: RegulationFile, org_name: str | None = None) -> dict:
    return DecisionRuleOut(
        rule_id=rule.rule_id, rule_key=rule.rule_key, scenario=rule.scenario, rule_type=rule.rule_type,
        priority=rule.priority, status=rule.status, file_id=file.file_id, clause_id=clause.clause_id,
        source_kind=rule.source_kind, asset_version_id=rule.asset_version_id, retrieval_unit_id=rule.retrieval_unit_id,
        file_title=file.title, clause_no=clause.clause_no, currency=rule.currency,
        amount_min_minor=rule.amount_min_minor, amount_max_minor=rule.amount_max_minor,
        min_inclusive=rule.min_inclusive, max_inclusive=rule.max_inclusive, org_scope=rule.org_scope, org_name=org_name,
        conditions=rule.conditions or {}, approver_path=rule.approver_path or [],
        required_materials=rule.required_materials or [], risk_note=rule.risk_note,
        effective_from=rule.effective_from.isoformat() if rule.effective_from else None,
        effective_to=rule.effective_to.isoformat() if rule.effective_to else None,
        reviewed_by=rule.reviewed_by, reviewed_at=rule.reviewed_at.isoformat() if rule.reviewed_at else None,
        review_note=rule.review_note,
    ).model_dump()


async def _outputs(db, rows):
    scopes = {rule.org_scope for rule, _, _ in rows}
    names = dict((await db.execute(select(OrgUnit.path, OrgUnit.name).where(OrgUnit.path.in_(scopes)))).all()) if scopes else {}
    return [_out(rule, clause, file, names.get(rule.org_scope, "全部授权组织" if rule.org_scope == "/" else None)) for rule, clause, file in rows]


async def _rule_row(db: AsyncSession, rule_id: str, user, perms, statuses: list[str] | None = None):
    rows = await load_rule_sources(db, user, perms, rule_id=rule_id, statuses=statuses)
    return rows[0] if rows else None


@router.get("", response_model=None)
async def list_rules(
    scenario: str | None = None,
    status: str | None = None,
    _: object = Depends(require_roles("R2", "R3", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, perms = ctx
    statuses = [status] if status else (["pending_review", "current"] if user.role == "R2" else None)
    rows = await load_rule_sources(db, user, perms, scenario=scenario, statuses=statuses, effective=status == "pending_review")
    return ok(await _outputs(db, rows))


@router.post("", response_model=None)
async def create_rule(
    body: DecisionRuleCreate,
    creator=Depends(require_roles("R3", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    """Create a review-required rule anchored to a current, effective clause."""
    user, perms = ctx
    source = await source_for_create(db, body, user, perms)
    if source is None:
        raise BadRequestError("规则依据必须是当前有效且有权限访问的制度条款")
    _source_clause, source_file = source
    if body.source_kind == "regulation" and not is_authority_verified(source_file):
        raise BadRequestError("请先由维护者确认资料来源可靠，再配置办理规则")
    existing = (
        await db.execute(
            select(DecisionRule.rule_id).where(
                DecisionRule.rule_key == body.rule_key,
                DecisionRule.status.in_([DecisionRuleStatus.PENDING_REVIEW.value, DecisionRuleStatus.CURRENT.value]),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise BadRequestError("该规则标识已有待审核或现行版本，请先处理原规则")
    if body.activate_now:
        await _validate_activation_scope(db, body.org_scope, perms)
    rule = DecisionRule(**body.model_dump(exclude={"activate_now", "activation_note"}), created_by=creator.user_id)
    if body.activate_now:
        rule.status = "current"
        rule.reviewed_by = creator.user_id
        rule.reviewed_at = datetime.now(timezone.utc)
        rule.review_note = "[维护者确认] " + body.activation_note.strip()
    db.add(rule)
    await db.flush()
    scenario_key = getattr(body.scenario, "value", body.scenario)
    task = (await db.execute(select(GovernanceTask).where(
        GovernanceTask.task_key == f"rule:{scenario_key}:{body.clause_id}"
    ))).scalar_one_or_none()
    if task is not None:
        task.status = "resolved"
        task.resolved_by = creator.user_id
        task.resolved_at = datetime.now(timezone.utc)
        task.resolution_note = "维护者已确认启用办理规则" if body.activate_now else "已形成规则草案并进入可选审核"
    await record_audit(
        db, actor_id=creator.user_id, action="rule.created", target_type="decision_rule", target_id=rule.rule_id,
        detail=json.dumps({"rule_key": rule.rule_key, "scenario": rule.scenario, "source_clause": rule.clause_id,
            "activation_method": "maintainer" if body.activate_now else "review", "activation_note": body.activation_note.strip()}, ensure_ascii=False),
    )
    await db.commit()
    clause, file = source
    return ok((await _outputs(db, [(rule, clause, file)]))[0])


class RuleActivationRequest(BaseModel):
    note: str = Field(min_length=1, max_length=512)


@router.post("/{rule_id}/activate", response_model=None)
async def activate_rule(rule_id: str, body: RuleActivationRequest,
    maintainer=Depends(require_roles("R3", "R4")), ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    user, perms = ctx
    if not body.note.strip():
        raise BadRequestError("请确认已对照原文核对规则口径")
    rows = await load_rule_sources(db, user, perms, rule_id=rule_id, statuses=["pending_review"], effective=True, require_authority=True)
    if not rows:
        raise NotFoundError("规则不存在、已处理或来源尚未确认可用")
    rule, clause, file = rows[0]
    await _validate_activation_scope(db, rule.org_scope, perms)
    if not rule.approver_path or not all(isinstance(step, str) and step.strip() for step in rule.approver_path):
        raise BadRequestError("规则必须具有可读办理路径")
    now = datetime.now(timezone.utc)
    result = await db.execute(update(DecisionRule).where(DecisionRule.rule_id == rule_id, DecisionRule.status == "pending_review").values(
        status="current", reviewed_by=maintainer.user_id, reviewed_at=now, review_note="[维护者确认] " + body.note.strip()))
    if result.rowcount != 1:
        raise BadRequestError("该规则已处理，请刷新")
    await record_audit(db, actor_id=maintainer.user_id, action="rule.maintainer.activated", target_type="decision_rule", target_id=rule_id,
        detail=json.dumps({"note": body.note.strip(), "source_kind": rule.source_kind}, ensure_ascii=False))
    await db.commit()
    await db.refresh(rule)
    return ok((await _outputs(db, [(rule, clause, file)]))[0])


@router.get("/sources", response_model=None)
async def rule_sources(
    source_kind: str = "regulation", file_id: str | None = None,
    asset_version_id: str | None = None, keyword: str = "",
    offset: int = Query(0, ge=0), limit: int = Query(80, ge=1, le=200),
    _: object = Depends(require_roles("R2", "R3", "R4")),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db),
):
    """Select an explicitly verified source before encoding an executable rule."""
    user, perms = ctx
    if source_kind not in {"regulation", "asset"}:
        raise BadRequestError("未知规则来源类型")
    if not file_id and not asset_version_id:
        readable_text = func.trim(func.replace(func.replace(func.replace(Clause.content, "\n", ""), "\r", ""), "\t", ""))
        readable_clause = select(Clause.clause_id).where(
            Clause.file_id == RegulationFile.file_id, Clause.status == "current",
            readable_text != "", build_filter(user, perms, Clause.secret_level),
        ).correlate(RegulationFile).exists()
        files = list((await db.execute(select(RegulationFile).where(regulation_effective_filter(date.today()), build_filter(user, perms), readable_clause).order_by(RegulationFile.title))).scalars())
        eligible_versions = asset_source_statement(user, perms, effective=True).with_only_columns(AssetVersion.version_id).distinct()
        rows = (await db.execute(select(AssetVersion, KnowledgeAsset).join(KnowledgeAsset, KnowledgeAsset.asset_id == AssetVersion.asset_id).where(AssetVersion.version_id.in_(eligible_versions)).order_by(KnowledgeAsset.title))).all()
        usable_assets = [(v, a) for v, a in rows if not asset_authority_gaps(a, v)]
        represented_legacy = {v.legacy_file_id for v, _asset in usable_assets if v.legacy_file_id}
        # The complete compound source can include normative annexes/forms or
        # several split regulations. Suppress only its explicitly mapped parent.
        # If it is unusable, a readable, confirmed legacy source remains available.
        sources = [{"source_kind": "regulation", "file_id": f.file_id, "title": f.title, "version": f.version} for f in files if f.file_id not in represented_legacy and is_authority_verified(f)]
        sources.extend({"source_kind": "asset", "file_id": a.asset_id, "asset_version_id": v.version_id, "title": a.title, "version": v.version_label} for v, a in usable_assets)
        return ok({"sources": sources, "units": [], "total": 0})
    if source_kind == "asset":
        stmt = asset_source_statement(user, perms, effective=True).where(AssetVersion.version_id == asset_version_id)
        if keyword.strip():
            stmt = stmt.where(or_(RetrievalUnit.text.contains(keyword.strip()), RetrievalUnit.title.contains(keyword.strip())))
        total = int((await db.execute(select(func.count()).select_from(stmt.with_only_columns(RetrievalUnit.unit_id).distinct().subquery()))).scalar() or 0)
        # A unit can have several source spans; paginate by unique unit identity.
        ids = stmt.with_only_columns(RetrievalUnit.unit_id).distinct().order_by(RetrievalUnit.unit_id).offset(offset).limit(limit)
        rows = (await db.execute(stmt.where(RetrievalUnit.unit_id.in_(ids)).order_by(RetrievalUnit.unit_id))).all()
        units = {}
        for row in rows:
            if asset_authority_gaps(row[2], row[1]):
                continue
            clause, file = normalise_asset_source(row)
            units.setdefault(clause.clause_id, {"source_kind": "asset", "file_id": file.file_id, "clause_id": clause.clause_id, "clause_no": clause.clause_no, "content": clause.content, "asset_version_id": row[1].version_id, "retrieval_unit_id": clause.clause_id, "source_page": clause.source_page, "source_locator": clause.source_locator, "content_hash": clause.content_hash})
        return ok({"sources": [], "units": list(units.values()), "total": total if units else 0})
    rows = (await db.execute(select(Clause, RegulationFile).join(RegulationFile, Clause.file_id == RegulationFile.file_id).where(Clause.file_id == file_id, Clause.status == "current", regulation_effective_filter(date.today()), build_filter(user, perms, Clause.secret_level)))).all()
    clauses = sort_clauses([c for c, f in rows if is_authority_verified(f) and (not keyword.strip() or keyword.strip() in c.content or keyword.strip() in c.clause_no)])
    return ok({"sources": [], "total": len(clauses), "units": [{"source_kind": "regulation", "file_id": c.file_id, "clause_id": c.clause_id, "clause_no": c.clause_no, "content": c.content, "source_page": c.source_page, "source_locator": c.source_locator, "content_hash": c.content_hash} for c in clauses[offset:offset+limit]]})


@router.get("/reviews/pending", response_model=None)
async def pending_rule_reviews(
    _: object = Depends(require_roles("R2", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, perms = ctx
    rows = await load_rule_sources(db, user, perms, statuses=["pending_review"], effective=True)
    return ok(await _outputs(db, rows))


@router.get("/coverage", response_model=None)
async def rule_coverage_candidates(
    ctx=Depends(get_user_context),
    _: object = Depends(require_roles("R2", "R3", "R4")),
    db: AsyncSession = Depends(get_db),
):
    """Return evidence-backed candidate clauses; never creates active rules."""
    user, perms = ctx
    active_rule_count = int((await db.execute(
        select(func.count()).select_from(DecisionRule).where(DecisionRule.status.in_(["pending_review", "current"]))
    )).scalar() or 0)
    result = await build_rule_candidates(db, user, perms)
    return ok({
        "target_scenarios": 5,
        "candidate_count": len(result),
        "active_rule_count": active_rule_count,
        "items": result,
    })


@router.post("/{rule_id}/review", response_model=None)
async def review_rule(
    rule_id: str,
    body: DecisionRuleReviewRequest,
    reviewer=Depends(require_roles("R2", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, perms = ctx
    row = await _rule_row(db, rule_id, user, perms, [DecisionRuleStatus.PENDING_REVIEW.value])
    if row is None:
        raise NotFoundError("待审核规则不存在、已处理或无权限")
    rule, clause, file = row
    note = body.note.strip()
    if not body.approved and not note:
        raise BadRequestError("驳回规则时必须填写审核意见")
    if body.approved:
        eligible = await load_rule_sources(db, user, perms, rule_id=rule_id, statuses=["pending_review"], effective=True, require_authority=True)
        if not eligible:
            raise BadRequestError("规则依据制度尚未完成权威元数据核验，不能发布规则")
        if file.status != "current" or (file.effective_date and file.effective_date > date.today()) or (file.expiry_date and file.expiry_date < date.today()):
            raise BadRequestError("规则依据制度当前未生效，不能发布规则")
        next_status = DecisionRuleStatus.CURRENT.value
        action = "rule.review.approved"
    else:
        next_status = DecisionRuleStatus.REJECTED.value
        action = "rule.review.rejected"
    changed = await db.execute(update(DecisionRule).where(DecisionRule.rule_id == rule_id, DecisionRule.status == DecisionRuleStatus.PENDING_REVIEW.value).values(status=next_status, reviewed_by=reviewer.user_id, reviewed_at=datetime.now(timezone.utc), review_note=note or None))
    if changed.rowcount != 1:
        raise BadRequestError("规则已被其他人员处理，请刷新审核队列")
    await record_audit(
        db, actor_id=reviewer.user_id, action=action, target_type="decision_rule", target_id=rule.rule_id,
        detail=json.dumps({"rule_key": rule.rule_key, "note": note}, ensure_ascii=False),
    )
    await db.commit()
    return ok((await _outputs(db, [(rule, clause, file)]))[0])
