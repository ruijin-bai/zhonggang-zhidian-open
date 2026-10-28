"""Business-matter workflow: structured facts -> deterministic path -> review."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_user_context, require_roles
from app.core.exceptions import BadRequestError, ForbiddenError, NotFoundError, ok
from app.db.enums import BusinessCaseStatus
from app.db.models.business_case import BusinessCase
from app.db.models.org import OrgUnit
from app.db.models.user import User
from app.db.models.qa import QASession
from app.db.session import get_db
from app.schemas.business_case import BusinessCaseCreate, BusinessCaseOut, BusinessCaseReviewRequest, BusinessCaseUpdate
from app.services.audit import record_audit
from app.services.rule.evaluator import RuleEvaluationService
from app.services.rule.evidence import load_rule_sources

router = APIRouter(prefix="/cases", tags=["cases"])


def _out(case: BusinessCase, org_name: str | None = None) -> dict:
    return BusinessCaseOut(
        case_id=case.case_id, case_no=case.case_no, requester_id=case.requester_id,
        scenario=case.scenario, title=case.title, org_path=case.org_path, org_name=org_name, project_code=case.project_code,
        amount_minor=case.amount_minor, currency=case.currency, facts=case.facts or {}, status=case.status,
        risk_level=case.risk_level, need_human=case.need_human, decision_summary=case.decision_summary,
        decision_snapshot=case.decision_snapshot or {},
        evaluated_at=case.evaluated_at.isoformat() if case.evaluated_at else None,
        reviewed_by=case.reviewed_by, reviewed_at=case.reviewed_at.isoformat() if case.reviewed_at else None,
        review_note=case.review_note,
    ).model_dump()


async def _outs(db: AsyncSession, cases: list[BusinessCase]) -> list[dict]:
    if not cases:
        return []
    names = dict((await db.execute(select(OrgUnit.path, OrgUnit.name).where(OrgUnit.path.in_({case.org_path for case in cases})))).all())
    return [_out(case, names.get(case.org_path)) for case in cases]


async def _one_out(db: AsyncSession, case: BusinessCase) -> dict:
    return (await _outs(db, [case]))[0]


async def _validated_org_path(db: AsyncSession, user: User, permissions, requested: str | None) -> str:
    own_org = await db.get(OrgUnit, user.org_id) if user.org_id else None
    if own_org is None:
        raise BadRequestError("当前账号尚未绑定有效办理组织，请先联系管理员完成绑定")
    target = (requested.strip() if requested else own_org.path).rstrip("/") or "/"
    if not _in_scope(target, permissions):
        raise ForbiddenError("办理组织不在你的数据权限范围内")
    org = (await db.execute(select(OrgUnit).where(OrgUnit.path == target).limit(1))).scalar_one_or_none()
    if org is None:
        raise BadRequestError("办理组织不存在，请选择已登记的组织")
    return org.path


def _in_scope(path: str, permissions) -> bool:
    return any(path == perm.org_scope.rstrip("/") or path.startswith(perm.org_scope.rstrip("/") + "/") for perm in permissions)


async def _validated_source_facts(db: AsyncSession, user: User, facts: dict) -> dict:
    """Keep a real, owned consultation link; query text cannot forge its identity."""
    result = dict(facts)
    source_id = result.get("source_session")
    if not source_id:
        result.pop("source_session", None)
        return result
    if not isinstance(source_id, str):
        raise BadRequestError("咨询来源标识无效")
    source = await db.get(QASession, source_id)
    if source is None or source.user_id != user.user_id or source.is_evaluation:
        raise NotFoundError("咨询记录不存在或不属于当前账号")
    result["source_question"] = source.question
    return result


def _case_scope_filter(permissions):
    if any(perm.org_scope == "/" for perm in permissions):
        return True
    # Substring avoids SQL LIKE wildcard interpretation in an organisation name.
    return or_(*[
        or_(BusinessCase.org_path == perm.org_scope.rstrip("/"),
            func.substr(BusinessCase.org_path, 1, len(perm.org_scope.rstrip("/")) + 1) == perm.org_scope.rstrip("/") + "/")
        for perm in permissions
    ]) if permissions else False


def _fact_fields(rules) -> dict[str, list[dict]]:
    """Offer only fields from already-authorised applicable rules; never infer facts."""
    reserved = {"urgent", "description", "source_question", "source_session", "amount", "amount_minor", "currency",
                "org_path", "org_scope", "project_code", "scenario", "title", "金额", "币种", "紧急事项"}
    labels = {"project_type": "项目类型", "procurement_method": "采购方式", "employment_type": "用工类型",
              "contract_type": "合同类型", "overseas": "境外事项", "is_overseas": "境外事项", "country": "所在国家",
              "country_scope": "国家范围", "org_level": "组织层级"}
    grouped: dict[str, dict[str, dict]] = {}
    for rule in rules:
        fields = grouped.setdefault(rule.scenario, {})
        for key, expected in (rule.conditions or {}).items():
            if key in reserved:
                continue
            field = fields.setdefault(key, {"key": key, "label": labels.get(key, key), "kind": "enum", "options": [], "types": set(), "complex": False})
            values = expected if isinstance(expected, list) else [expected]
            if not values:
                field["complex"] = True
            for value in values:
                if value is None or isinstance(value, (dict, list)) or not isinstance(value, (str, bool, int, float)):
                    field["complex"] = True
                    continue
                kind = "boolean" if isinstance(value, bool) else "number" if isinstance(value, (int, float)) else "enum"
                field["types"].add(kind)
                if not any(isinstance(option["value"], bool) == isinstance(value, bool) and option["value"] == value for option in field["options"]):
                    field["options"].append({"value": value, "label": "是" if value is True else "否" if value is False else str(value)})
    output: dict[str, list[dict]] = {}
    for scenario, fields in grouped.items():
        output[scenario] = []
        for field in fields.values():
            kinds = field.pop("types")
            complex_value = field.pop("complex")
            field["kind"] = "manual" if complex_value else next(iter(kinds)) if len(kinds) == 1 else "enum"
            if field["kind"] == "boolean":
                field["options"] = [{"value": True, "label": "是"}, {"value": False, "label": "否"}]
            output[scenario].append(field)
    return output


@router.post("", response_model=None)
async def create_case(
    body: BusinessCaseCreate,
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, perms = ctx
    org_path = await _validated_org_path(db, user, perms, body.org_path)
    facts = await _validated_source_facts(db, user, body.facts)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    case = BusinessCase(
        case_no=f"BC-{stamp}", requester_id=user.user_id, scenario=body.scenario,
        title=body.title, org_path=org_path, project_code=body.project_code,
        amount_minor=body.amount_minor, currency=body.currency, facts=facts,
    )
    db.add(case)
    await db.flush()
    await record_audit(db, actor_id=user.user_id, action="case.created", target_type="business_case", target_id=case.case_id)
    await db.commit()
    return ok(await _one_out(db, case))


@router.get("/context", response_model=None)
async def case_context(ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    """Expose the current user's organisation as display data, not an editable ID."""
    user, perms = ctx
    org = await db.get(OrgUnit, user.org_id) if user.org_id else None
    today = date.today()
    target_org = org.path if org else "/"
    rows = await load_rule_sources(db, user, perms, statuses=["current"], effective=True, require_authority=True)
    counts: dict[str, int] = {}
    applicable_rules = []
    for rule, _clause, _file in rows:
        scope = rule.org_scope.rstrip("/")
        if target_org != scope and not target_org.startswith(scope + "/"):
            continue
        if (rule.effective_from and rule.effective_from > today) or (rule.effective_to and rule.effective_to < today):
            continue
        counts[rule.scenario] = counts.get(rule.scenario, 0) + 1
        applicable_rules.append(rule)
    return ok({
        "org_path": org.path if org else "/",
        "org_name": org.name if org else "未绑定组织",
        "rule_counts": counts,
        "fact_fields": _fact_fields(applicable_rules),
    })


@router.get("/mine", response_model=None)
async def my_cases(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cases = list(
        (await db.execute(select(BusinessCase).where(BusinessCase.requester_id == user.user_id).order_by(BusinessCase.created_at.desc())))
        .scalars()
    )
    return ok(await _outs(db, cases))


@router.get("/review-queue", response_model=None)
async def case_review_queue(
    _: object = Depends(require_roles("R2", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    _, perms = ctx
    cases = list(
        (await db.execute(
            select(BusinessCase).where(BusinessCase.status == BusinessCaseStatus.REVIEW_REQUIRED.value, _case_scope_filter(perms)).order_by(BusinessCase.evaluated_at.asc())
        )).scalars()
    )
    return ok(await _outs(db, cases))


@router.get("/{case_id}", response_model=None)
async def case_detail(case_id: str, ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    user, perms = ctx
    case = await db.get(BusinessCase, case_id)
    if case is None:
        raise NotFoundError("事项不存在")
    if case.requester_id != user.user_id and (user.role not in {"R2", "R4"} or not _in_scope(case.org_path, perms)):
        raise ForbiddenError()
    return ok(await _one_out(db, case))


@router.post("/{case_id}/evaluate", response_model=None)
async def evaluate_case(
    case_id: str,
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, perms = ctx
    case = await db.get(BusinessCase, case_id)
    if case is None:
        raise NotFoundError("事项不存在")
    if case.requester_id != user.user_id:
        raise ForbiddenError("只能校验本人发起的事项")
    if case.status not in {BusinessCaseStatus.DRAFT.value, BusinessCaseStatus.RETURNED.value}:
        raise BadRequestError("仅草稿或已退回事项可重新校验；已形成的办理结论须保留")
    if not _in_scope(case.org_path, perms):
        raise ForbiddenError("事项所属组织不在你的数据权限范围内")
    result = await RuleEvaluationService().evaluate(
        db, user=user, permissions=perms, scenario=case.scenario, org_path=case.org_path,
        amount_minor=case.amount_minor, currency=case.currency, facts=case.facts or {},
    )
    case.decision_snapshot = result
    case.decision_summary = result["summary"]
    case.need_human = bool(result["need_human"])
    case.risk_level = result["risk_level"]
    case.status = BusinessCaseStatus.REVIEW_REQUIRED.value if case.need_human else BusinessCaseStatus.ASSESSED.value
    case.evaluated_at = datetime.now(timezone.utc)
    if case.need_human:
        case.submitted_at = case.evaluated_at
    await record_audit(
        db, actor_id=user.user_id, action="case.evaluated", target_type="business_case", target_id=case.case_id,
        detail=json.dumps({"reason_code": result["reason_code"], "matched_rule_ids": result["matched_rule_ids"]}, ensure_ascii=False),
    )
    await db.commit()
    return ok(await _one_out(db, case))


@router.put("/{case_id}", response_model=None)
async def update_case(
    case_id: str,
    body: BusinessCaseUpdate,
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    """Keep the case identity while replacing facts before a fresh evaluation."""
    user, perms = ctx
    case = await db.get(BusinessCase, case_id)
    if case is None:
        raise NotFoundError("事项不存在")
    if case.requester_id != user.user_id:
        raise ForbiddenError("只能修改本人发起的事项")
    if case.status not in {BusinessCaseStatus.DRAFT.value, BusinessCaseStatus.RETURNED.value}:
        raise BadRequestError("仅草稿或已退回事项可修改；请保留已审核的办理结论")
    org_path = await _validated_org_path(db, user, perms, body.org_path or case.org_path)
    facts = await _validated_source_facts(db, user, body.facts)
    previous = {
        "scenario": case.scenario, "title": case.title, "org_path": case.org_path,
        "project_code": case.project_code, "amount_minor": case.amount_minor,
        "currency": case.currency, "facts": case.facts, "status": case.status,
        "decision_snapshot": case.decision_snapshot, "review_note": case.review_note,
        "reviewed_by": case.reviewed_by, "reviewed_at": case.reviewed_at.isoformat() if case.reviewed_at else None,
    }
    case.scenario = body.scenario
    case.title = body.title
    case.org_path = org_path
    case.project_code = body.project_code
    case.amount_minor = body.amount_minor
    case.currency = body.currency
    case.facts = facts
    # Stale guidance must disappear as soon as its underlying facts change.
    case.status = BusinessCaseStatus.DRAFT.value
    case.need_human = True
    case.risk_level = "medium"
    case.decision_summary = None
    case.decision_snapshot = {}
    case.evaluated_at = None
    case.submitted_at = None
    case.reviewed_by = None
    case.reviewed_at = None
    case.review_note = None
    await record_audit(
        db, actor_id=user.user_id, action="case.updated", target_type="business_case", target_id=case.case_id,
        detail=json.dumps({"previous": previous, "facts": body.model_dump()}, ensure_ascii=False),
    )
    await db.commit()
    return ok(await _one_out(db, case))


@router.post("/{case_id}/review", response_model=None)
async def review_case(
    case_id: str,
    body: BusinessCaseReviewRequest,
    reviewer=Depends(require_roles("R2", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    _, perms = ctx
    case = await db.get(BusinessCase, case_id)
    if case is None or case.status != BusinessCaseStatus.REVIEW_REQUIRED.value:
        raise NotFoundError("待复核事项不存在或已处理")
    if not _in_scope(case.org_path, perms):
        raise ForbiddenError("事项所属组织不在你的复核权限范围内")
    case.status = BusinessCaseStatus.CONFIRMED.value if body.confirmed else BusinessCaseStatus.RETURNED.value
    case.reviewed_by = reviewer.user_id
    case.reviewed_at = datetime.now(timezone.utc)
    case.review_note = body.note.strip()
    # 人工复核的结论写回决策快照：员工拿到的最终审批路径/材料来自复核人，可追溯
    if body.approver_path or body.required_materials:
        snapshot = dict(case.decision_snapshot or {})
        snapshot["manual_review"] = {
            "confirmed": body.confirmed,
            "approver_path": body.approver_path,
            "required_materials": body.required_materials,
            "reviewed_by": reviewer.user_id,
            "reviewed_at": case.reviewed_at.isoformat(),
        }
        if body.approver_path:
            snapshot["approver_path"] = body.approver_path
            snapshot["approval_path"] = body.approver_path
        if body.required_materials or body.confirmed:
            snapshot["required_materials"] = body.required_materials
            snapshot["materials"] = body.required_materials
        case.decision_snapshot = snapshot
        case.decision_summary = f"[人工复核] {body.note.strip()}"
    await record_audit(
        db, actor_id=reviewer.user_id, action="case.review.confirmed" if body.confirmed else "case.review.returned",
        target_type="business_case", target_id=case.case_id, detail=json.dumps({"note": case.review_note}, ensure_ascii=False),
    )
    await db.commit()
    return ok(await _one_out(db, case))
