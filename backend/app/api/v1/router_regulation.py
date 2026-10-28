"""Regulation ingestion, clause detail and annotation endpoints (T05 / T11)."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, delete as sa_delete, func, or_, update
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.api.v1.deps import get_user_context, require_roles
from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError, ok
from app.adapters.storage.object_store import get_object_store
from app.db.base import gen_id
from app.db.enums import PushStatus, RegulationStatus
from app.db.models.clause import Clause
from app.db.models.ingestion import IngestionJob
from app.db.models.governance_task import GovernanceTask
from app.db.models.org import OrgUnit
from app.db.models.push import PushRecord, PushReceipt
from app.db.models.user import User
from app.db.models.regulation import RegulationFile
from app.db.models.regulation_document import RegulationDocument
from app.db.models.tag import Tag, regulation_tag
from app.db.models.rule import DecisionRule
from app.db.session import get_db
from app.schemas.regulation import (
    AnnotationRequest,
    ClauseDetailOut,
    ClauseOut,
    RegulationDocumentOut,
    RegulationGovernanceGap,
    RegulationMetadataUpdate,
    RegulationOut,
    RegulationReviewRequest,
    RegulationUploadResponse,
)
from app.services.ingestion.ingest_job import process_ingestion_job, schedule_ingestion
from app.services.ingestion.parser import inspect_machine_readability
from app.services.permission.rbac import build_filter
from app.services.regulation.versioning import validate_version_submission
from app.services.regulation.versioning import publish_regulation, announce_regulation_publication
from app.services.audit import record_audit
from app.services.impact.analyzer import generate_change_impact
from app.services.governance import metadata_missing_fields
from app.services.governance_state import authority_gaps, is_authority_verified, source_verification, valid_source_confirmation
from app.utils.clause_order import sort_clauses

router = APIRouter(prefix="/regulations", tags=["regulations"])


def _release_visible_to_employee(user) -> bool:
    # R2 receives unpublished content only through the dedicated review API.
    # Its ordinary library experience must mirror the employee release view.
    return user.role in {"R1", "R2"}


def _currently_effective_filter():
    today = date.today()
    return and_(
        RegulationFile.status == RegulationStatus.CURRENT.value,
        or_(RegulationFile.effective_date.is_(None), RegulationFile.effective_date <= today),
        or_(RegulationFile.expiry_date.is_(None), RegulationFile.expiry_date >= today),
    )


def _display_source(value: str | None) -> str | None:
    """Never expose a workstation's absolute import path through the API."""
    if not value:
        return value
    normalized = value.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] or "内部制度库"


def _regulation_payload(f: RegulationFile, *, has_job: bool = False, tags: list[str] | None = None, document_count: int = 0) -> dict:
    return RegulationOut(
        file_id=f.file_id,
        regulation_code=f.regulation_code,
        title=f.title,
        source=_display_source(f.source),
        version=f.version,
        status=f.status,
        effective_date=str(f.effective_date) if f.effective_date else None,
        expiry_date=str(f.expiry_date) if f.expiry_date else None,
        replaces_file_id=f.replaces_file_id,
        ingest_error=f.ingest_error,
        reviewed_by=f.reviewed_by,
        reviewed_at=f.reviewed_at.isoformat() if f.reviewed_at else None,
        review_note=f.review_note,
        has_original=bool(f.object_key),
        has_ingestion_job=has_job,
        owner_org=f.owner_org,
        org_path=f.org_path,
        secret_level=f.secret_level,
        domain=f.domain,
        lang=f.lang,
        tags=tags or [],
        document_count=document_count,
        authority_verified=is_authority_verified(f),
        authority_gaps=authority_gaps(f),
        source_verification=source_verification(f),
        parse_backend=f.parse_backend,
        parse_quality_score=f.parse_quality_score,
        parse_quality_report=f.parse_quality_report or {},
    ).model_dump()


async def _load_tags(db: AsyncSession, file_ids: list[str]) -> dict[str, list[str]]:
    """Return {file_id: [分类标签, ...]} for the given regulations."""
    if not file_ids:
        return {}
    rows = (
        await db.execute(
            select(regulation_tag.c.file_id, Tag.tag_value)
            .join(Tag, Tag.tag_id == regulation_tag.c.tag_id)
            .where(regulation_tag.c.file_id.in_(file_ids), Tag.tag_type == "制度分类")
        )
    ).all()
    result: dict[str, list[str]] = {}
    for file_id, tag_value in rows:
        result.setdefault(file_id, []).append(tag_value)
    return result


async def _load_document_counts(db: AsyncSession, file_ids: list[str]) -> dict[str, int]:
    if not file_ids:
        return {}
    rows = (
        await db.execute(
            select(RegulationDocument.file_id, func.count())
            .where(RegulationDocument.file_id.in_(file_ids))
            .group_by(RegulationDocument.file_id)
        )
    ).all()
    return {file_id: count for file_id, count in rows}


@router.post("/upload", response_model=None)
async def upload(
    file: UploadFile = File(...),
    title: str = Form(...),
    regulation_code: str = Form(""),
    source: str = Form(""),
    version: str = Form("v1"),
    effective_date: date | None = Form(None),
    expiry_date: date | None = Form(None),
    replaces_file_id: str | None = Form(None),
    owner_org: str | None = Form(None),
    org_path: str = Form("/"),
    secret_level: str = Form("internal"),
    domain: str = Form("*"),
    lang: str = Form("zh"),
    source_confirmed: bool = Form(False),
    source_note: str = Form("我确认上传资料来源可靠，可用于制度咨询与办理准备。"),
    admin: User = Depends(require_roles("R3", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    normalized_code = regulation_code.strip()
    normalized_version = version.strip()
    replaces_file_id = replaces_file_id or None
    if source_confirmed and (not source_note.strip() or len(source_note) > 512):
        raise BadRequestError("请用不超过512字说明本人确认资料可靠")
    if not normalized_version:
        raise BadRequestError("版本号不能为空")
    resolved_effective_date = effective_date
    if expiry_date is not None and effective_date is not None and expiry_date < effective_date:
        raise BadRequestError("失效日期不能早于生效日期")
    await validate_version_submission(
        db,
        regulation_code=normalized_code,
        version=normalized_version,
        replaces_file_id=replaces_file_id,
    )
    data = await file.read()
    if Path(file.filename or "").suffix.lower() == ".doc":
        raise BadRequestError("暂不支持旧版 .doc 格式，请转为 .docx 或 PDF 后上传")
    readability = inspect_machine_readability(file.filename or "", data)
    if not readability["accepted"]:
        raise BadRequestError(readability["message"])
    resolved_path = org_path
    if owner_org:
        org = await db.get(OrgUnit, owner_org)
        if org is None:
            raise BadRequestError("所选责任部门不存在")
        resolved_path = org.path
    user, permissions = ctx
    proposed = RegulationFile(org_path=resolved_path, secret_level=secret_level, domain=domain)
    from sqlalchemy import literal
    from app.services.permission.rbac import build_asset_filter
    allowed = await db.scalar(select(build_asset_filter(user, permissions,
        org_path=literal(proposed.org_path), secret_level=literal(proposed.secret_level), domain=literal(proposed.domain))))
    if not allowed:
        raise BadRequestError("上传资料范围不在当前账号权限内")
    if replaces_file_id:
        prior = await db.scalar(select(RegulationFile).where(RegulationFile.file_id == replaces_file_id, build_filter(user, permissions)))
        if prior is None:
            raise NotFoundError("被替代资料不存在或无权限")
    store = get_object_store()
    object_key = store.put_object(f"{gen_id('obj')}_{file.filename}", data, file.content_type or "application/octet-stream")

    # 先落地一条 processing 状态的制度记录，解析（切分/向量化/标注）在后台异步完成，
    # 上传接口立即返回，避免同步等待 LLM 导致的 20s 超时。
    reg = RegulationFile(
        regulation_code=normalized_code,
        title=title,
        source=source,
        version=normalized_version,
        effective_date=resolved_effective_date,
        expiry_date=expiry_date,
        replaces_file_id=replaces_file_id,
        owner_org=owner_org,
        org_path=resolved_path,
        secret_level=secret_level,
        domain=domain,
        lang=lang,
        object_key=object_key,
        status="processing",
    )
    db.add(reg)
    await db.flush()
    if source_confirmed:
        reg.source_confirmation = _confirmation(reg, admin.user_id, source_note)
        await record_audit(db, actor_id=admin.user_id, action="regulation.source.confirmed", target_type="regulation_file", target_id=reg.file_id,
            detail=json.dumps({"method": "maintainer", "note": reg.source_confirmation["note"]}, ensure_ascii=False))
    job = IngestionJob(file_id=reg.file_id, source_filename=file.filename or "document")
    db.add(job)
    await db.flush()
    await db.commit()

    if settings.INGEST_ASYNC:
        schedule_ingestion(job.job_id)
    else:
        await process_ingestion_job(job.job_id)
        await db.refresh(reg)
        await db.refresh(job)
        clause_count = len((await db.execute(select(Clause.clause_id).where(Clause.file_id == reg.file_id))).all())
        return ok(
            RegulationUploadResponse(
                file_id=reg.file_id,
                job_id=job.job_id,
                status=reg.status,
                clause_count=clause_count,
                ingest_error=reg.ingest_error,
            ).model_dump()
        )
    return ok(
        RegulationUploadResponse(file_id=reg.file_id, job_id=job.job_id, status=reg.status, clause_count=0).model_dump()
    )


def _confirmation(item, actor_id, note):
    value = (note or "").strip()
    if not value or len(value) > 512:
        raise BadRequestError("请用不超过512字说明本人确认资料可靠")
    return {"kind": "maintainer", "confirmed": True, "actor_id": actor_id,
        "confirmed_at": datetime.now(timezone.utc).isoformat(), "note": value,
        "file_id": item.file_id, "version": item.version, "object_key": item.object_key}


class SourceConfirmationsRequest(BaseModel):
    file_ids: list[str] = Field(min_length=1, max_length=2000)
    note: str = Field(default="我确认这些上传资料来源可靠，可用于制度咨询与办理准备。", min_length=1, max_length=512)


@router.post("/source-confirmations", response_model=None)
async def confirm_sources(body: SourceConfirmationsRequest,
    admin: User = Depends(require_roles("R3", "R4")), ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    user, permissions = ctx
    identifiers = set(body.file_ids)
    files = list((await db.scalars(select(RegulationFile).where(
        RegulationFile.file_id.in_(identifiers), build_filter(user, permissions),
        RegulationFile.status.in_(["current", "pending_review"])))) .all())
    if len(files) != len(identifiers):
        raise NotFoundError("部分资料不存在、尚未完成处理或不在当前账号权限内")
    readable = set((await db.scalars(select(Clause.file_id).where(Clause.file_id.in_(identifiers), Clause.status == "current", func.trim(Clause.content) != "").distinct())).all())
    if readable != identifiers:
        raise BadRequestError("部分资料尚无可读原文，请先完成处理")
    for item in files:
        item.source_confirmation = _confirmation(item, admin.user_id, body.note)
        if item.status == "pending_review":
            from app.services.eval.publish_gate import evaluate_publish_candidate
            readiness = await evaluate_publish_candidate(db, item)
            if not readiness["passed"]:
                raise BadRequestError(readiness["reason"])
            await publish_regulation(db, item)
            await announce_regulation_publication(db, item)
        await record_audit(db, actor_id=admin.user_id, action="regulation.source.confirmed", target_type="regulation_file", target_id=item.file_id,
            detail=json.dumps({"method": "maintainer", "note": body.note.strip()}, ensure_ascii=False))
    # The migrated V2 rendition must retain the same usable-source decision,
    # otherwise duplicate-source preference would reintroduce the old block.
    from app.db.models.asset import AssetVersion, KnowledgeAsset
    from app.services.assets.publication import version_filter, publication_report, stamp_source_confirmation
    mirrored = []
    rows = (await db.execute(select(AssetVersion, KnowledgeAsset).join(KnowledgeAsset, KnowledgeAsset.asset_id == AssetVersion.asset_id).where(
        AssetVersion.legacy_file_id.in_(identifiers), AssetVersion.release_state == "current", AssetVersion.ingestion_state == "ready",
        version_filter(user, permissions)))).all()
    for version, asset in rows:
        report = await publication_report(db, version, asset, user, permissions, require_authority=False)
        if report["publishable"]:
            stamp_source_confirmation(version, report, admin, body.note.strip())
            mirrored.append(version.version_id)
            await record_audit(db, actor_id=admin.user_id, action="asset.source.confirmed", target_type="asset_version", target_id=version.version_id,
                detail=json.dumps({"method": "maintainer", "legacy_file_id": version.legacy_file_id}, ensure_ascii=False))
    await db.commit()
    return ok({"count": len(files), "file_ids": sorted(identifiers), "source_verification": "maintainer", "mirrored_asset_versions": mirrored})


def _job_payload(job: IngestionJob) -> dict:
    return {
        "job_id": job.job_id,
        "file_id": job.file_id,
        "status": job.status,
        "attempt_count": job.attempt_count,
        "last_error": job.last_error,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.get("/{file_id}/ingestion", response_model=None)
async def ingestion_status(
    file_id: str,
    _: object = Depends(require_roles("R3", "R4")),
    db: AsyncSession = Depends(get_db),
):
    job = (
        await db.execute(select(IngestionJob).where(IngestionJob.file_id == file_id))
    ).scalar_one_or_none()
    if job is None:
        raise NotFoundError("入库任务不存在")
    return ok(_job_payload(job))


@router.post("/{file_id}/ingestion/retry", response_model=None)
async def retry_ingestion(
    file_id: str,
    _: object = Depends(require_roles("R3", "R4")),
    db: AsyncSession = Depends(get_db),
):
    regulation = await db.get(RegulationFile, file_id)
    job = (
        await db.execute(select(IngestionJob).where(IngestionJob.file_id == file_id))
    ).scalar_one_or_none()
    if regulation is None or job is None:
        raise NotFoundError("制度或入库任务不存在")
    if regulation.status != "failed" or job.status != "failed":
        raise BadRequestError("仅失败的入库任务可重试")
    # A failed gate may already have persisted candidate clauses.  Remove only
    # this failed version's data before replaying the original object.
    await db.execute(sa_delete(Clause).where(Clause.file_id == file_id))
    regulation.status = "processing"
    regulation.ingest_error = None
    regulation.parse_quality_score = None
    regulation.parse_quality_report = {}
    job.status = "pending"
    job.last_error = None
    job.finished_at = None
    await db.commit()
    if settings.INGEST_ASYNC:
        schedule_ingestion(job.job_id)
    else:
        await process_ingestion_job(job.job_id)
        await db.refresh(regulation)
        await db.refresh(job)
    return ok({"file_id": file_id, "status": regulation.status, "job": _job_payload(job)})


@router.post("/{file_id}/reparse", response_model=None)
async def reparse_regulation(
    file_id: str,
    admin: User = Depends(require_roles("R3", "R4")),
    db: AsyncSession = Depends(get_db),
):
    """Safely reparse an existing asset; old clauses survive any parse/gate failure."""
    from app.services.eval.publish_gate import evaluate_publish_candidate
    from app.services.ingestion.annotator import append_clauses_to_file
    from app.services.ingestion.embed_job import embed_pending_clauses
    from app.services.ingestion.structured_parser import parse_document_structured

    regulation = await db.get(RegulationFile, file_id)
    if regulation is None:
        raise NotFoundError("制度不存在")
    if not regulation.object_key:
        raise BadRequestError("该制度没有可重解析的原始文件")
    source = get_object_store().get_object(regulation.object_key)
    if source is None:
        raise BadRequestError("制度原件不可读取，未改动现有条款")
    job = (
        await db.execute(select(IngestionJob).where(IngestionJob.file_id == file_id))
    ).scalar_one_or_none()
    filename = job.source_filename if job else f"{regulation.title}{Path(regulation.object_key).suffix}"
    clauses, report = await parse_document_structured(filename, source)
    if not report.passed:
        raise BadRequestError("重解析质量未通过，现有条款已保留：" + "；".join(report.warnings))

    previous_status = regulation.status
    try:
        old_clause_ids = list((await db.execute(
            select(Clause.clause_id).where(Clause.file_id == file_id, Clause.status == "current")
        )).scalars())
        # Preserve superseded clauses as immutable audit evidence. New clauses
        # are the only current retrieval units after the transaction commits.
        await db.execute(
            update(Clause).where(Clause.clause_id.in_(old_clause_ids)).values(status="isolated")
        )
        if old_clause_ids:
            await db.execute(
                update(DecisionRule)
                .where(DecisionRule.clause_id.in_(old_clause_ids), DecisionRule.status == "current")
                .values(status="retired")
            )
        await append_clauses_to_file(db, file_id, clauses, secret_level=regulation.secret_level)
        regulation.parse_backend = report.backend
        regulation.parse_quality_score = report.score
        regulation.parse_quality_report = report.model_dump()
        regulation.ingest_error = None
        await embed_pending_clauses(db)
        readiness = await evaluate_publish_candidate(db, regulation)
        if not readiness["passed"]:
            raise BadRequestError("重解析检索校验未通过，现有条款已保留")
        regulation.status = previous_status
        await record_audit(
            db, actor_id=admin.user_id, action="regulation.reparsed",
            target_type="regulation_file", target_id=file_id,
            detail=json.dumps({
                "backend": report.backend, "quality_score": report.score,
                "clause_count": len(clauses), "warnings": report.warnings,
            }, ensure_ascii=False),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return ok({
        "file_id": file_id, "status": previous_status, "clause_count": len(clauses),
        "parse_backend": report.backend, "parse_quality_score": report.score,
        "parse_quality_report": report.model_dump(),
    })


@router.get("", response_model=None)
async def list_regulations(
    tag: str | None = None,
    status: str | None = None,
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, perms = ctx
    stmt = select(RegulationFile).where(build_filter(user, perms)).order_by(RegulationFile.created_at.desc())
    if _release_visible_to_employee(user):
        stmt = stmt.where(_currently_effective_filter())
    if status:
        # 显式状态查询（审核/管理场景）：不做 employee current 过滤，否则互斥恒空
        stmt = stmt.where(RegulationFile.status == status)
    if tag:
        stmt = stmt.where(
            RegulationFile.file_id.in_(
                select(regulation_tag.c.file_id)
                .join(Tag, Tag.tag_id == regulation_tag.c.tag_id)
                .where(Tag.tag_value == tag, Tag.tag_type == "制度分类")
            )
        )
    files = list((await db.execute(stmt)).scalars().all())
    file_ids = [f.file_id for f in files]
    job_file_ids = set()
    if file_ids:
        job_file_ids = set(
            (await db.execute(select(IngestionJob.file_id).where(IngestionJob.file_id.in_(file_ids)))).scalars().all()
        )
    tags_map = await _load_tags(db, file_ids)
    counts_map = await _load_document_counts(db, file_ids)
    readable_counts = dict((await db.execute(select(Clause.file_id, func.count()).join(RegulationFile).where(
        Clause.file_id.in_(file_ids), Clause.status == "current", func.trim(Clause.content) != "",
        build_filter(user, perms, Clause.secret_level)).group_by(Clause.file_id))).all()) if file_ids else {}
    return ok(
        [
            {**_regulation_payload(f, has_job=f.file_id in job_file_ids, tags=tags_map.get(f.file_id), document_count=counts_map.get(f.file_id, 0)),
             "clause_count": readable_counts.get(f.file_id, 0)}
            for f in files
        ]
    )


@router.get("/categories", response_model=None)
async def list_categories(ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    """Return the classification tags with their regulation counts."""
    user, perms = ctx
    visible = select(RegulationFile.file_id).where(build_filter(user, perms))
    if _release_visible_to_employee(user):
        visible = visible.where(_currently_effective_filter())
    rows = (
        await db.execute(
            select(Tag.tag_value, func.count(regulation_tag.c.file_id))
            .join(regulation_tag, regulation_tag.c.tag_id == Tag.tag_id)
            .where(Tag.tag_type == "制度分类", regulation_tag.c.file_id.in_(visible))
            .group_by(Tag.tag_value)
            .order_by(func.count(regulation_tag.c.file_id).desc())
        )
    ).all()
    return ok([{"name": name, "count": count} for name, count in rows])


@router.get("/governance/gaps", response_model=None)
async def governance_gaps(
    _: object = Depends(require_roles("R3", "R4")),
    db: AsyncSession = Depends(get_db),
):
    files = list((await db.execute(select(RegulationFile).order_by(RegulationFile.title))).scalars().all())
    gaps = []
    for item in files:
        missing = []
        if not item.regulation_code or item.regulation_code.strip() == item.title.strip():
            missing.append("制度编码")
        if item.effective_date is None:
            missing.append("生效日期")
        if not item.owner_org:
            missing.append("责任部门")
        if not item.domain or item.domain == "*":
            missing.append("制度域")
        if missing:
            gaps.append(RegulationGovernanceGap(
                file_id=item.file_id, title=item.title, status=item.status,
                missing_fields=missing, regulation_code=item.regulation_code,
                effective_date=item.effective_date.isoformat() if item.effective_date else None,
                owner_org=item.owner_org, domain=item.domain or "*",
            ).model_dump())
    return ok({"total": len(gaps), "items": gaps})


@router.post("/{file_id}/metadata", response_model=None)
async def update_metadata(
    file_id: str,
    body: RegulationMetadataUpdate,
    admin: User = Depends(require_roles("R3", "R4")),
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(RegulationFile, file_id)
    if item is None:
        raise NotFoundError("制度不存在")
    values = body.model_dump(exclude_unset=True, exclude={"evidence_note"})
    effective = values.get("effective_date", item.effective_date)
    expiry = values.get("expiry_date", item.expiry_date)
    if effective and expiry and expiry < effective:
        raise BadRequestError("失效日期不能早于生效日期")
    for field, value in values.items():
        if isinstance(value, str):
            value = value.strip() or None
        setattr(item, field, value)
    task = (await db.execute(select(GovernanceTask).where(
        GovernanceTask.task_key == f"metadata:{item.file_id}"
    ))).scalar_one_or_none()
    remaining = metadata_missing_fields(item)
    if task is not None:
        task.missing_fields = remaining
        task.evidence = {
            **(task.evidence or {}),
            "last_confirmation": {
                "fields": sorted(values), "note": body.evidence_note.strip(),
                "actor_id": admin.user_id, "confirmed_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        if not remaining:
            task.status = "resolved"
            task.resolved_by = admin.user_id
            task.resolved_at = datetime.now(timezone.utc)
            task.resolution_note = body.evidence_note.strip()
    await record_audit(
        db, actor_id=admin.user_id, action="regulation.metadata.updated",
        target_type="regulation_file", target_id=item.file_id,
        detail=json.dumps({"fields": sorted(values), "evidence_note": body.evidence_note.strip()}, ensure_ascii=False),
    )
    await db.commit()
    return ok(_regulation_payload(item))


@router.get("/reviews/pending", response_model=None)
async def list_pending_reviews(
    _: object = Depends(require_roles("R2", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    """Return release-ready candidates for accountable business review."""
    user, perms = ctx
    files = list(
        (
            await db.execute(
                select(RegulationFile)
                .where(
                    RegulationFile.status == RegulationStatus.PENDING_REVIEW.value,
                    build_filter(user, perms),
                )
                .order_by(RegulationFile.created_at.asc())
            )
        ).scalars()
    )
    file_ids = [f.file_id for f in files]
    job_file_ids = set()
    if file_ids:
        job_file_ids = set(
            (await db.execute(select(IngestionJob.file_id).where(IngestionJob.file_id.in_(file_ids)))).scalars().all()
        )
    return ok([_regulation_payload(f, has_job=f.file_id in job_file_ids) for f in files])


@router.get("/reviews/{file_id}/preview", response_model=None)
async def preview_pending_review(
    file_id: str,
    _: object = Depends(require_roles("R2", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    """Preview the exact candidate and clauses on which a review is based."""
    user, perms = ctx
    f = (
        await db.execute(
            select(RegulationFile).where(
                RegulationFile.file_id == file_id,
                RegulationFile.status == RegulationStatus.PENDING_REVIEW.value,
                build_filter(user, perms),
            )
        )
    ).scalar_one_or_none()
    if f is None:
        raise NotFoundError("待审核制度不存在、已处理或无权限")
    clauses = sort_clauses(
        (
            await db.execute(
                select(Clause)
                .join(RegulationFile, Clause.file_id == RegulationFile.file_id)
                .where(
                    Clause.file_id == file_id,
                    Clause.status == "current",
                    build_filter(user, perms, Clause.secret_level),
                )
            )
        ).scalars()
    )
    clause_dtos = [
        ClauseOut(
            clause_id=c.clause_id, file_id=c.file_id, chapter=c.chapter, clause_no=c.clause_no,
            content=c.content, permission_level=c.permission_level, secret_level=c.secret_level,
            scenario_tags=c.scenario_tags or [], status=c.status,
            source_page=c.source_page, source_locator=c.source_locator, content_hash=c.content_hash,
            heading_path=c.heading_path or [], block_type=c.block_type,
        ).model_dump()
        for c in clauses
    ]
    return ok({**_regulation_payload(f, has_job=True), "clause_count": len(clause_dtos), "clauses": clause_dtos})


@router.post("/{file_id}/review", response_model=None)
async def review_regulation(
    file_id: str,
    body: RegulationReviewRequest,
    reviewer=Depends(require_roles("R2", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject a release-ready regulation version.

    Technical checks happen during ingestion. This endpoint records the
    optional formal business decision. Maintainers can also explicitly confirm
    a readable source through the self-confirmation workflow.
    """
    user, perms = ctx
    regulation = (
        await db.execute(
            select(RegulationFile).where(
                RegulationFile.file_id == file_id,
                RegulationFile.status == RegulationStatus.PENDING_REVIEW.value,
                build_filter(user, perms),
            )
        )
    ).scalar_one_or_none()
    if regulation is None:
        raise NotFoundError("待审核制度不存在、已处理或无权限")
    note = body.note.strip()
    if not body.approved and not note:
        raise BadRequestError("驳回时必须填写审核意见")
    now = datetime.now(timezone.utc)
    regulation.reviewed_by = reviewer.user_id
    regulation.reviewed_at = now
    regulation.review_note = note or None
    if body.approved:
        replaced_file = await db.get(RegulationFile, regulation.replaces_file_id) if regulation.replaces_file_id else None
        await publish_regulation(db, regulation)
        impact = await generate_change_impact(db, new_file=regulation, old_file=replaced_file, actor_id=reviewer.user_id)
        # 发布即推送：制度更新必须触达员工，治理闭环的最后一环
        push = PushRecord(
            file_id=regulation.file_id,
            status=PushStatus.SENT.value,
            digest=f"《{regulation.title}》{'已更新发布' if replaced_file else '已发布生效'}"
                   f"（{regulation.version or 'v1'}），请查阅最新条款。",
            created_by=reviewer.user_id,
        )
        db.add(push)
        await db.flush()
        recipients = list((await db.execute(select(User.user_id))).scalars().all())
        for uid in recipients:
            db.add(PushReceipt(push_id=push.push_id, user_id=uid))
        action = "regulation.review.approved"
    else:
        regulation.status = RegulationStatus.REJECTED.value
        action = "regulation.review.rejected"
    await record_audit(
        db,
        actor_id=reviewer.user_id,
        action=action,
        target_type="regulation_file",
        target_id=regulation.file_id,
        detail=json.dumps({"regulation_code": regulation.regulation_code, "version": regulation.version, "note": note}, ensure_ascii=False),
    )
    await db.commit()
    payload = _regulation_payload(regulation, has_job=True)
    if body.approved and impact is not None:
        payload["impact_id"] = impact.impact_id
    return ok(payload)


@router.post("/{file_id}/review/resubmit", response_model=None)
async def resubmit_regulation_review(
    file_id: str,
    _: object = Depends(require_roles("R3", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    """Return a rejected, unchanged candidate to the business review queue."""
    user, perms = ctx
    regulation = (
        await db.execute(
            select(RegulationFile).where(
                RegulationFile.file_id == file_id,
                RegulationFile.status == RegulationStatus.REJECTED.value,
                build_filter(user, perms),
            )
        )
    ).scalar_one_or_none()
    if regulation is None:
        raise NotFoundError("被驳回制度不存在或无权限")
    regulation.status = RegulationStatus.PENDING_REVIEW.value
    regulation.reviewed_by = None
    regulation.reviewed_at = None
    regulation.review_note = None
    await record_audit(
        db,
        actor_id=user.user_id,
        action="regulation.review.resubmitted",
        target_type="regulation_file",
        target_id=regulation.file_id,
    )
    await db.commit()
    return ok(_regulation_payload(regulation, has_job=True))


class BatchReviewRequest(BaseModel):
    file_ids: list[str]
    approved: bool = True
    note: str = "批量审核"


@router.post("/reviews/batch", response_model=None)
async def batch_review_regulations(
    body: BatchReviewRequest,
    reviewer=Depends(require_roles("R2", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    """批量审核：制度库初始化/批量导入后逐份点击不现实。

    每份制度仍逐条走发布+影响分析+推送，审计逐条记录，责任不稀释。
    """
    user, perms = ctx
    if not body.file_ids:
        raise BadRequestError("请选择要审核的制度")
    results = {"approved": 0, "skipped": 0}
    for file_id in body.file_ids[:200]:
        regulation = (
            await db.execute(
                select(RegulationFile).where(
                    RegulationFile.file_id == file_id,
                    RegulationFile.status == RegulationStatus.PENDING_REVIEW.value,
                    build_filter(user, perms),
                )
            )
        ).scalar_one_or_none()
        if regulation is None:
            results["skipped"] += 1
            continue
        now = datetime.now(timezone.utc)
        regulation.reviewed_by = reviewer.user_id
        regulation.reviewed_at = now
        regulation.review_note = body.note
        if body.approved:
            replaced = await db.get(RegulationFile, regulation.replaces_file_id) if regulation.replaces_file_id else None
            await publish_regulation(db, regulation)
            await generate_change_impact(db, new_file=regulation, old_file=replaced, actor_id=reviewer.user_id)
            push = PushRecord(
                file_id=regulation.file_id,
                status=PushStatus.SENT.value,
                digest=f"《{regulation.title}》已发布生效（{regulation.version or 'v1'}），请查阅最新条款。",
                created_by=reviewer.user_id,
            )
            db.add(push)
            await db.flush()
            for uid in (await db.execute(select(User.user_id))).scalars().all():
                db.add(PushReceipt(push_id=push.push_id, user_id=uid))
        else:
            regulation.status = RegulationStatus.REJECTED.value
        await record_audit(
            db, actor_id=reviewer.user_id,
            action="regulation.review.batch_approved" if body.approved else "regulation.review.batch_rejected",
            target_type="regulation_file", target_id=regulation.file_id,
        )
        results["approved"] += 1
    await db.commit()
    return ok(results)


@router.get("/{file_id}", response_model=None)
async def regulation_detail(file_id: str, ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    user, perms = ctx
    stmt = select(RegulationFile).where(RegulationFile.file_id == file_id, build_filter(user, perms))
    if _release_visible_to_employee(user):
        stmt = stmt.where(_currently_effective_filter())
    f = (await db.execute(stmt)).scalar_one_or_none()
    if f is None:
        raise NotFoundError("制度文件不存在或无权限")
    has_job = (await db.execute(select(IngestionJob.file_id).where(IngestionJob.file_id == file_id))).scalar_one_or_none() is not None
    tags = (await _load_tags(db, [file_id])).get(file_id, [])
    docs = list(
        (await db.execute(
            select(RegulationDocument).where(RegulationDocument.file_id == file_id).order_by(RegulationDocument.sort_order)
        )).scalars().all()
    )
    documents = [
        RegulationDocumentOut(
            doc_id=d.doc_id, doc_type=d.doc_type, title=d.title, filename=d.filename,
            mime=d.mime, object_key=d.object_key,
        ).model_dump()
        for d in docs
    ]
    return ok(
        {**_regulation_payload(f, has_job=has_job, tags=tags, document_count=len(docs)), "documents": documents}
    )


@router.get("/{file_id}/clauses", response_model=None)
async def list_clauses(file_id: str, ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    user, perms = ctx
    stmt = (
        select(Clause)
        .join(RegulationFile, Clause.file_id == RegulationFile.file_id)
        .where(
            Clause.file_id == file_id,
            Clause.status == "current",
            build_filter(user, perms, Clause.secret_level),
        )
    )
    if _release_visible_to_employee(user):
        stmt = stmt.where(_currently_effective_filter())
    clauses = sort_clauses((await db.execute(stmt)).scalars().all())
    return ok(
        [
            ClauseOut(
                clause_id=c.clause_id, file_id=c.file_id, chapter=c.chapter, clause_no=c.clause_no,
                content=c.content, permission_level=c.permission_level, secret_level=c.secret_level,
                scenario_tags=c.scenario_tags or [], status=c.status,
                source_page=c.source_page, source_locator=c.source_locator, content_hash=c.content_hash,
            ).model_dump()
            for c in clauses
        ]
    )


@router.get("/clauses/{clause_id}", response_model=None)
async def clause_detail(clause_id: str, ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    user, perms = ctx
    stmt = (
        select(Clause, RegulationFile)
        .join(RegulationFile, Clause.file_id == RegulationFile.file_id)
        .where(Clause.clause_id == clause_id, build_filter(user, perms, Clause.secret_level))
    )
    if _release_visible_to_employee(user):
        stmt = stmt.where(_currently_effective_filter())
    row = (await db.execute(stmt)).first()
    if row is None:
        raise NotFoundError("条款不存在或无权限")
    clause, file = row
    return ok(
        ClauseDetailOut(
            clause_id=clause.clause_id, file_id=clause.file_id, chapter=clause.chapter,
            clause_no=clause.clause_no, content=clause.content, permission_level=clause.permission_level,
            secret_level=clause.secret_level, scenario_tags=clause.scenario_tags or [], status=clause.status,
            source_page=clause.source_page, source_locator=clause.source_locator, content_hash=clause.content_hash,
            file_title=file.title, file_version=file.version, file_status=file.status,
            tags=clause.scenario_tags or [],
        ).model_dump()
    )


@router.post("/clauses/{clause_id}/annotate", response_model=None)
async def annotate_clause(
    clause_id: str,
    body: AnnotationRequest,
    _: object = Depends(require_roles("R3", "R4")),
    db: AsyncSession = Depends(get_db),
):
    clause = await db.get(Clause, clause_id)
    if clause is None:
        raise NotFoundError("条款不存在")
    if body.scenario_tags is not None:
        clause.scenario_tags = body.scenario_tags
    if body.secret_level is not None:
        clause.secret_level = body.secret_level
    if body.permission_level is not None:
        clause.permission_level = body.permission_level
    await db.flush()
    await db.commit()
    return ok({"clause_id": clause.clause_id})


@router.delete("/{file_id}", response_model=None)
async def delete_regulation(
    file_id: str,
    _: object = Depends(require_roles("R3", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    """Delete a regulation file, its clauses, and the original stored object.

    R3/R4 only. RBAC filter is applied so a user can only delete files they
    are permitted to see.
    """
    user, perms = ctx
    stmt = select(RegulationFile).where(RegulationFile.file_id == file_id, build_filter(user, perms))
    if _release_visible_to_employee(user):
        stmt = stmt.where(_currently_effective_filter())
    f = (await db.execute(stmt)).scalar_one_or_none()
    if f is None:
        raise NotFoundError("制度文件不存在或无权限")

    # 1) remove original file from object store
    if f.object_key:
        try:
            get_object_store().delete_object(f.object_key)
        except Exception:  # noqa: BLE001
            pass  # 文件缺失不阻断删除

    # 2) remove clauses (explicit, robust regardless of ORM cascade)
    await db.execute(sa_delete(Clause).where(Clause.file_id == file_id))
    # 3) remove the regulation file record
    await db.delete(f)
    await db.commit()
    return ok({"file_id": file_id, "deleted": True})


@router.get("/{file_id}/download", response_model=None)
async def download_regulation(
    file_id: str,
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    """Download the original uploaded document (PDF/Word/TXT)."""
    user, perms = ctx
    stmt = select(RegulationFile).where(RegulationFile.file_id == file_id, build_filter(user, perms))
    if _release_visible_to_employee(user):
        stmt = stmt.where(_currently_effective_filter())
    f = (await db.execute(stmt)).scalar_one_or_none()
    if f is None:
        raise NotFoundError("制度文件不存在或无权限")
    if not f.object_key:
        raise NotFoundError("该制度无原始文件可供下载")

    data = await asyncio.to_thread(lambda: get_object_store().get_object(f.object_key))
    if data is None:
        raise NotFoundError("原始文件未找到（可能已被清理）")

    # 用标题 + 原始文件后缀作为下载文件名（RFC5987 兼容中文）。
    # filename= 段必须是 ASCII，故用 file_id 作回退；中文真名放在 filename*= 段。
    suffix = Path(f.object_key).suffix or ""
    filename = f"{f.title}{suffix}"
    ascii_fallback = f"{f.file_id}{suffix}"
    headers = {
        "Content-Disposition": f"attachment; filename={ascii_fallback}; filename*=UTF-8''{quote(filename)}"
    }
    return StreamingResponse(
        iter([data]),
        media_type="application/octet-stream",
        headers=headers,
    )


@router.get("/{file_id}/documents/{doc_id}/download", response_model=None)
async def download_regulation_document(
    file_id: str, doc_id: str, ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, perms = ctx
    stmt = select(RegulationDocument, RegulationFile).join(RegulationFile, RegulationDocument.file_id == RegulationFile.file_id).where(RegulationDocument.file_id == file_id, RegulationDocument.doc_id == doc_id, build_filter(user, perms))
    if _release_visible_to_employee(user):
        stmt = stmt.where(_currently_effective_filter())
    row = (await db.execute(stmt)).first()
    if row is None:
        raise NotFoundError("制度文件不存在或无权限")
    document, _file = row
    if not document.object_key:
        raise NotFoundError("该文件尚无可下载原件")
    data = await asyncio.to_thread(lambda: get_object_store().get_object(document.object_key))
    if data is None:
        raise NotFoundError("原件未找到，请联系资料管理员")
    suffix = Path(document.filename).suffix
    name = Path(document.filename.replace("\\", "/")).name or f"{document.title}{suffix}"
    return StreamingResponse(iter([data]), media_type=document.mime or "application/octet-stream", headers={"Content-Disposition": f"attachment; filename={document.doc_id}{suffix}; filename*=UTF-8''{quote(name)}"})


@router.get("/{file_id}/preview", response_model=None)
async def preview_regulation(
    file_id: str,
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated preview: regulation metadata + all (current) clauses with AI annotations."""
    user, perms = ctx
    stmt = select(RegulationFile).where(RegulationFile.file_id == file_id, build_filter(user, perms))
    if _release_visible_to_employee(user):
        stmt = stmt.where(_currently_effective_filter())
    f = (await db.execute(stmt)).scalar_one_or_none()
    if f is None:
        raise NotFoundError("制度文件不存在或无权限")

    cstmt = (
        select(Clause)
        .join(RegulationFile, Clause.file_id == RegulationFile.file_id)
        .where(
            Clause.file_id == file_id,
            Clause.status == "current",
            build_filter(user, perms, Clause.secret_level),
        )
    )
    clauses = sort_clauses((await db.execute(cstmt)).scalars().all())
    clause_dtos = [
        ClauseOut(
            clause_id=c.clause_id, file_id=c.file_id, chapter=c.chapter, clause_no=c.clause_no,
            content=c.content, permission_level=c.permission_level, secret_level=c.secret_level,
            scenario_tags=c.scenario_tags or [], status=c.status,
            source_page=c.source_page, source_locator=c.source_locator, content_hash=c.content_hash,
        ).model_dump()
        for c in clauses
    ]
    meta = _regulation_payload(
        f,
        has_job=(await db.execute(select(IngestionJob.file_id).where(IngestionJob.file_id == file_id))).scalar_one_or_none() is not None,
    )
    return ok({**meta, "clause_count": len(clause_dtos), "clauses": clause_dtos})
