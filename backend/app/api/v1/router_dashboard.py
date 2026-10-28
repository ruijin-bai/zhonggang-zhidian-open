"""Permission-aware workbench counts and explicitly sampled quality signals."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import false, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_user_context, require_roles
from app.core.exceptions import ok
from app.db.enums import ReadStatus
from app.db.models.business_case import BusinessCase
from app.db.models.asset import AssetVersion, KnowledgeAsset
from app.db.models.clause import Clause
from app.db.models.eval import TestCase, TestRun
from app.db.models.feedback import QAFeedback
from app.db.models.impact import ChangeImpactItem, ChangeImpactRun
from app.db.models.ingestion import IngestionJob
from app.db.models.push import PushReceipt, PushRecord
from app.db.models.qa import QACitation, QASession
from app.db.models.regulation import RegulationFile
from app.db.models.relation import Relation
from app.db.models.rule import DecisionRule
from app.db.session import get_db
from app.schemas.dashboard import QualityDashboard
from app.services.eval.retrieval_benchmark import load_retrieval_benchmark
from app.services.assets.publication import version_filter
from app.services.assets.catalog import readable_version_unit_counts
from app.services.permission.rbac import build_filter
from app.services.rule.evidence import load_rule_sources
from app.services.rule.evaluator import regulation_effective_filter

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


async def _count(db: AsyncSession, statement) -> int:
    return int((await db.execute(statement)).scalar() or 0)


def _ratio(numerator: int, denominator: int) -> float | None:
    # A missing sample is different from an observed 0% result.
    return round(numerator / denominator, 3) if denominator else None


def _case_scope(permissions):
    conditions = []
    for permission in permissions:
        scope = permission.org_scope.rstrip("/")
        conditions.append(
            true() if not scope else or_(
                BusinessCase.org_path == scope,
                BusinessCase.org_path.startswith(scope + "/", autoescape=True),
            )
        )
    return or_(*conditions) if conditions else false()


async def _active_rule_count(db, user, permissions):
    today = date.today()
    rows = await load_rule_sources(
        db, user, permissions, statuses=["current"], effective=True, require_authority=True, as_of=today,
    )
    return sum(1 for rule, _clause, _file in rows if
        (rule.effective_from is None or rule.effective_from <= today)
        and (rule.effective_to is None or rule.effective_to >= today))


def _impact_query(user, permissions):
    return select(func.count()).select_from(ChangeImpactItem).join(
        ChangeImpactRun, ChangeImpactItem.impact_id == ChangeImpactRun.impact_id
    ).join(RegulationFile, ChangeImpactRun.new_file_id == RegulationFile.file_id).where(
        ChangeImpactItem.status != "resolved", build_filter(user, permissions)
    )


def _feedback_query():
    return select(func.count()).select_from(QAFeedback).join(
        QASession, QAFeedback.session_id == QASession.session_id
    ).where(QASession.is_evaluation.is_(False), QAFeedback.type == "correct", QAFeedback.resolved.is_(False))


def _pending_asset_query(user, permissions):
    return select(func.count()).select_from(AssetVersion).join(
        KnowledgeAsset, AssetVersion.asset_id == KnowledgeAsset.asset_id
    ).where(AssetVersion.release_state == "pending_review", version_filter(user, permissions))


async def _directory_count(db, user, permissions):
    """Match the directory: readable compound versions replace empty legacy containers."""
    legacy_query = select(RegulationFile.file_id).where(build_filter(user, permissions))
    if user.role in {"R1", "R2"}:
        legacy_query = legacy_query.where(regulation_effective_filter(date.today()))
    legacy_ids = set((await db.scalars(legacy_query)).all())
    readable_rows = (await db.execute(select(Clause.file_id, RegulationFile.status).join(RegulationFile).where(
        Clause.file_id.in_(legacy_ids), Clause.status == "current", func.trim(Clause.content) != "",
        build_filter(user, permissions, Clause.secret_level),
    ).distinct())).all() if legacy_ids else []
    readable_legacy = {file_id for file_id, status in readable_rows if status == "current"}
    empty_legacy = legacy_ids - {file_id for file_id, _status in readable_rows}
    candidates = (await db.execute(select(AssetVersion.version_id, AssetVersion.legacy_file_id).join(
        KnowledgeAsset, AssetVersion.asset_id == KnowledgeAsset.asset_id,
    ).where(
        version_filter(user, permissions), AssetVersion.release_state == "current", AssetVersion.ingestion_state == "ready",
        or_(AssetVersion.effective_date.is_(None), AssetVersion.effective_date <= date.today()),
        or_(AssetVersion.expiry_date.is_(None), AssetVersion.expiry_date >= date.today()),
    ))).all()
    readable_versions = await readable_version_unit_counts(db, user, permissions, [row.version_id for row in candidates])
    represented_containers = set()
    compound_count = 0
    for version_id, legacy_id in candidates:
        if not legacy_id:
            compound_count += 1
        elif legacy_id not in readable_legacy and readable_versions.get(version_id, 0) > 0:
            compound_count += 1
            if legacy_id in empty_legacy:
                represented_containers.add(legacy_id)
    return len(legacy_ids - represented_containers) + compound_count


@router.get("/workbench", response_model=None)
async def workbench(ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    """Each badge uses the permissions and status range of its destination."""
    user, permissions = ctx
    visible_ids = select(RegulationFile.file_id).where(build_filter(user, permissions))
    data = {
        "role": user.role,
        "my_case_total": await _count(db, select(func.count()).select_from(BusinessCase).where(BusinessCase.requester_id == user.user_id)),
        "my_case_open": await _count(db, select(func.count()).select_from(BusinessCase).where(
            BusinessCase.requester_id == user.user_id, BusinessCase.status.in_(["draft", "returned", "review_required"]),
        )),
        "unread_pushes": await _count(db, select(func.count(func.distinct(PushReceipt.push_id))).select_from(PushReceipt).join(
            PushRecord, PushReceipt.push_id == PushRecord.push_id
        ).where(PushReceipt.user_id == user.user_id, PushReceipt.read_status == ReadStatus.UNREAD.value, PushRecord.status == "sent")),
        "regulation_total": await _directory_count(db, user, permissions),
        "relation_count": await _count(db, select(func.count()).select_from(Relation).where(
            Relation.from_id.in_(visible_ids), Relation.to_id.in_(visible_ids),
        )) if user.role in {"R2", "R3", "R4"} else 0,
        "impact_open": await _count(db, _impact_query(user, permissions)) if user.role in {"R2", "R3", "R4"} else 0,
        "active_rules": await _active_rule_count(db, user, permissions) if user.role in {"R2", "R3", "R4"} else 0,
        "pending_rule_reviews": 0,
        "pending_regulation_reviews": 0,
        "pending_asset_reviews": 0,
        "pending_case_reviews": 0,
        "pending_feedbacks": 0,
        "ingestion_failures": 0,
    }
    if user.role in {"R2", "R3", "R4"}:
        # R3 can track submitted rule drafts in the rules page, although only
        # reviewers can approve them. Its badge must not remain permanently 0.
        data["pending_rule_reviews"] = len(await load_rule_sources(db, user, permissions, statuses=["pending_review"], effective=True))
    if user.role in {"R2", "R4"}:
        data.update({
            "pending_regulation_reviews": await _count(db, select(func.count()).select_from(RegulationFile).where(
                RegulationFile.status == "pending_review", build_filter(user, permissions),
            )),
            "pending_asset_reviews": await _count(db, _pending_asset_query(user, permissions)),
            "pending_case_reviews": await _count(db, select(func.count()).select_from(BusinessCase).where(
                BusinessCase.status == "review_required", _case_scope(permissions),
            )),
            "pending_feedbacks": await _count(db, _feedback_query()),
        })
    if user.role in {"R3", "R4"}:
        # Recovered failures stay in the audit ledger, not in today's actions.
        data["ingestion_failures"] = await _count(db, select(func.count()).select_from(IngestionJob).join(
            RegulationFile, IngestionJob.file_id == RegulationFile.file_id
        ).where(IngestionJob.status == "failed", RegulationFile.status == "failed", build_filter(user, permissions)))
    data["total_actions"] = sum(int(data[key]) for key in (
        "my_case_open", "unread_pushes", "pending_rule_reviews", "pending_regulation_reviews", "pending_asset_reviews",
        "pending_case_reviews", "pending_feedbacks", "ingestion_failures", "impact_open",
    ))
    return ok(data)


@router.get("/quality", response_model=None)
async def quality(
    _: object = Depends(require_roles("R2", "R4")),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db),
):
    user, permissions = ctx
    case_query = select(func.count()).select_from(BusinessCase).where(_case_scope(permissions))
    asset_query = select(func.count()).select_from(RegulationFile).where(build_filter(user, permissions))
    clause_query = select(func.count()).select_from(Clause).join(RegulationFile, Clause.file_id == RegulationFile.file_id).where(
        build_filter(user, permissions, Clause.secret_level)
    )
    live_qa = QASession.is_evaluation.is_(False)
    answered_cond = (live_qa, func.trim(QASession.answer_interpret, " \n\r\t") != "")
    qa_query = select(func.count()).select_from(QASession).where(live_qa)
    qa_total = await _count(db, qa_query)
    answered = await _count(db, qa_query.where(*answered_cond))
    need_human = await _count(db, qa_query.where(QASession.need_human.is_(True)))
    cited_sessions = await _count(db, select(func.count(func.distinct(QACitation.session_id))).select_from(QACitation).join(
        QASession, QACitation.session_id == QASession.session_id
    ).where(*answered_cond))
    confidence = (await db.execute(select(func.avg(QASession.confidence)).where(*answered_cond))).scalar()
    degraded = await _count(db, qa_query.where(*answered_cond, QASession.degraded.is_(True)))
    grounded = await _count(db, qa_query.where(*answered_cond, QASession.grounding_passed.is_(True)))
    authority_answers = await _count(db, qa_query.where(*answered_cond, QASession.authority_verified.is_(True)))

    run_query = select(func.count()).select_from(TestRun)
    total_runs = await _count(db, run_query)
    # A user can like and favourite one answer multiple times. Adoption counts
    # distinct answered sessions, so a single answer cannot exceed the sample.
    positive_sessions = await _count(db, select(func.count(func.distinct(QAFeedback.session_id))).select_from(QAFeedback).join(
        QASession, QAFeedback.session_id == QASession.session_id
    ).where(*answered_cond, QAFeedback.type.in_(["like", "favorite"])))
    distribution = (await db.execute(select(QAFeedback.type, func.count()).join(
        QASession, QAFeedback.session_id == QASession.session_id
    ).where(live_qa).group_by(QAFeedback.type))).all()
    clause_tags = (await db.execute(select(Clause.scenario_tags).join(
        RegulationFile, Clause.file_id == RegulationFile.file_id
    ).where(build_filter(user, permissions, Clause.secret_level)))).scalars().all()
    covered = {tag for tags in clause_tags for tag in (tags or [])}
    referenced = set((await db.execute(select(TestCase.scenario_tag).where(TestCase.scenario_tag.isnot(None)))).scalars().all())
    clause_total = await _count(db, clause_query)
    anchored_clauses = await _count(db, clause_query.where(Clause.content_hash.isnot(None), Clause.content_hash != ""))
    parsed_regulations = await _count(db, select(func.count(func.distinct(Clause.file_id))).select_from(Clause).join(
        RegulationFile, Clause.file_id == RegulationFile.file_id
    ).where(build_filter(user, permissions, Clause.secret_level)))
    from app.services.governance_state import is_authority_verified
    visible_current_sources = (await db.scalars(select(RegulationFile).where(
        build_filter(user, permissions), regulation_effective_filter(date.today())))).all()
    verified_sources = sum(is_authority_verified(source) for source in visible_current_sources)

    return ok(QualityDashboard(
        case_total=await _count(db, case_query),
        case_review_required=await _count(db, case_query.where(BusinessCase.status == "review_required")),
        case_confirmed=await _count(db, case_query.where(BusinessCase.status == "confirmed")),
        active_rule_count=await _active_rule_count(db, user, permissions),
        open_impact_count=await _count(db, _impact_query(user, permissions)),
        open_high_impact_count=await _count(db, _impact_query(user, permissions).where(ChangeImpactItem.severity == "high")),
        qa_total=qa_total, answered_total=answered, evaluation_run_total=total_runs,
        recall_rate=_ratio(await _count(db, run_query.where(TestRun.recall_match.is_(True))), total_runs),
        citation_rate=_ratio(await _count(db, run_query.where(TestRun.citation_match.is_(True))), total_runs),
        adopt_rate=_ratio(positive_sessions, answered),
        human_handoff_rate=_ratio(need_human, qa_total),
        realtime_citation_rate=_ratio(cited_sessions, answered),
        realtime_avg_confidence=round(float(confidence), 3) if confidence is not None else None,
        degraded_rate=_ratio(degraded, answered),
        grounding_rate=_ratio(grounded, answered),
        authority_answer_rate=_ratio(authority_answers, answered),
        correction_distribution=[{"type": kind, "count": count} for kind, count in distribution],
        uncovered_scenarios=sorted(covered - referenced)[:20],
        regulation_total=await _count(db, asset_query),
        regulation_current=await _count(db, asset_query.where(regulation_effective_filter(date.today()))),
        regulation_pending_review=await _count(db, asset_query.where(RegulationFile.status == "pending_review")),
        pending_asset_reviews=await _count(db, _pending_asset_query(user, permissions)),
        clause_total=clause_total, regulation_with_clauses=parsed_regulations,
        pending_feedback_count=await _count(db, _feedback_query()),
        regulation_authority_verified=verified_sources,
        source_anchor_rate=_ratio(anchored_clauses, clause_total),
        testset_total=await _count(db, select(func.count()).select_from(TestCase)),
        retrieval_smoke_total=len(load_retrieval_benchmark()),
        evaluation_grounding_rate=_ratio(await _count(db, run_query.where(TestRun.grounding_match.is_(True))), total_runs),
        evaluation_answer_rate=_ratio(await _count(db, run_query.where(TestRun.answer_match.is_(True))), total_runs),
        evaluation_authority_rate=_ratio(await _count(db, run_query.where(TestRun.authority_match.is_(True))), total_runs),
    ).model_dump())
