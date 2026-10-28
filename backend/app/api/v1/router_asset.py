"""V2 compound governance-asset administration and review APIs."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_user_context, require_roles
from app.core.exceptions import BadRequestError, NotFoundError, ok
from app.adapters.storage.object_store import get_object_store
from app.db.base import gen_id
from app.db.models.asset import (
    AssetDocument,
    AssetVersion,
    AssetVersionDocument,
    ContentNode,
    DocumentParseRun,
    KnowledgeAsset,
    RetrievalUnit, RetrievalUnitSource,
)
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.db.models.org import OrgUnit
from app.db.session import get_db
from app.services.assets.benchmark_manifest import BENCHMARK_TITLES
from app.services.assets.catalog import readable_version_unit_counts
from app.services.assets.migration import migrate_legacy_regulation
from app.services.assets.parse_service import parse_asset_document
from app.services.assets.taxonomy import taxonomy_payload
from app.services.assets.taxonomy import AssetType, DocumentRole, ParseDisposition
from app.services.assets.publication import (
    asset_filter, authority_gaps, publication_report, require_editable,
    source_fields, source_permission, version_filter, visible_document, visible_version,
    invalidate_source_confirmation, source_verification, stamp_source_confirmation,
)
from app.services.audit import record_audit
from app.services.permission.rbac import build_asset_filter, build_filter
from app.services.assets.retrieval_index import eligible_unit_predicates
from app.services.ingestion.parser import inspect_machine_readability


router = APIRouter(prefix="/assets", tags=["compound-assets"])


def _asset_payload(asset: KnowledgeAsset) -> dict:
    return {
        "asset_id": asset.asset_id,
        "asset_type": asset.asset_type,
        "title": asset.title,
        "business_code": asset.business_code,
        "owner_org": asset.owner_org,
        "org_path": asset.org_path,
        "secret_level": asset.secret_level,
        "domain": asset.domain,
        "status": asset.status,
    }


@router.get("/taxonomy", response_model=None)
async def get_taxonomy(ctx=Depends(get_user_context)):
    return ok(taxonomy_payload())


@router.get("/summary", response_model=None)
async def summary(
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, permissions = ctx
    visible_versions = select(AssetVersion.version_id).join(KnowledgeAsset).where(version_filter(user, permissions))
    visible_documents = (
        select(AssetDocument.document_id).join(AssetVersionDocument).join(AssetVersion).join(KnowledgeAsset)
        .where(version_filter(user, permissions, document=True))
    )
    async def count(stmt) -> int:
        return int((await db.execute(stmt)).scalar_one())

    parse_states = dict((await db.execute(
        select(DocumentParseRun.status, func.count())
        .where(DocumentParseRun.is_current.is_(True), DocumentParseRun.document_id.in_(visible_documents))
        .group_by(DocumentParseRun.status)
    )).all())
    version_states = dict((await db.execute(
        select(AssetVersion.ingestion_state, func.count())
        .where(AssetVersion.version_id.in_(visible_versions)).group_by(AssetVersion.ingestion_state)
    )).all())
    current_node_count = int((await db.execute(
        select(func.count())
        .select_from(ContentNode)
        .join(DocumentParseRun, DocumentParseRun.parse_run_id == ContentNode.parse_run_id)
        .where(DocumentParseRun.is_current.is_(True), DocumentParseRun.document_id.in_(visible_documents))
    )).scalar_one())
    return ok({
        "assets": await count(select(func.count(func.distinct(AssetVersion.asset_id))).where(AssetVersion.version_id.in_(visible_versions))),
        "versions": await count(select(func.count()).select_from(AssetVersion).where(AssetVersion.version_id.in_(visible_versions))),
        "documents": await count(select(func.count()).select_from(AssetDocument).where(AssetDocument.document_id.in_(visible_documents))),
        "content_nodes": current_node_count,
        "parse_states": parse_states,
        "version_ingestion_states": version_states,
        "benchmark_target": len(BENCHMARK_TITLES),
    })


@router.get("", response_model=None)
async def list_assets(
    asset_type: str | None = None,
    ingestion_state: str | None = None,
    published_only: bool = False,
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, permissions = ctx
    stmt = (
        select(KnowledgeAsset, AssetVersion, func.count(AssetVersionDocument.link_id).filter(asset_filter(user, permissions, document=True)))
        .join(AssetVersion, AssetVersion.asset_id == KnowledgeAsset.asset_id)
        .outerjoin(AssetVersionDocument, AssetVersionDocument.version_id == AssetVersion.version_id)
        .outerjoin(AssetDocument, AssetDocument.document_id == AssetVersionDocument.document_id)
        .group_by(KnowledgeAsset.asset_id, AssetVersion.version_id)
        .where(version_filter(user, permissions))
        .order_by(KnowledgeAsset.title, AssetVersion.version_label)
    )
    if asset_type:
        stmt = stmt.where(KnowledgeAsset.asset_type == asset_type)
    if ingestion_state:
        stmt = stmt.where(AssetVersion.ingestion_state == ingestion_state)
    if published_only:
        stmt = stmt.where(AssetVersion.release_state == "current", AssetVersion.ingestion_state == "ready",
            or_(AssetVersion.effective_date.is_(None), AssetVersion.effective_date <= date.today()),
            or_(AssetVersion.expiry_date.is_(None), AssetVersion.expiry_date >= date.today()))
    rows = (await db.execute(stmt)).all()
    readable_counts = await readable_version_unit_counts(
        db, user, permissions, [version.version_id for _asset, version, _count in rows],
    )
    return ok([
        {
            **_asset_payload(asset),
            "version_id": version.version_id,
            "version_label": version.version_label,
            "issue_no": version.issue_no,
            "release_state": version.release_state,
            "ingestion_state": version.ingestion_state,
            "effective_date": version.effective_date.isoformat() if version.effective_date else None,
            "expiry_date": version.expiry_date.isoformat() if version.expiry_date else None,
            "document_count": document_count,
            "readable_unit_count": readable_counts.get(version.version_id, 0),
            "legacy_file_id": version.legacy_file_id,
            "authority_gaps": authority_gaps(asset, version),
            "source_verification": source_verification(asset, version),
            "authority_verified": version.release_state == "current" and version.ingestion_state == "ready"
                and (version.effective_date is None or version.effective_date <= date.today())
                and (version.expiry_date is None or version.expiry_date >= date.today())
                and source_verification(asset, version) != "unconfirmed",
        }
        for asset, version, document_count in rows
    ])


@router.post("", response_model=None)
async def create_asset_package(
    files: list[UploadFile] = File(...),
    title: str = Form(...),
    asset_type: str = Form(...),
    business_code: str = Form(""),
    domain: str = Form("*"),
    version_label: str = Form("v1"),
    manifest_json: str = Form("[]"),
    actor: User = Depends(require_roles("R3", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    """Create one governed asset package from multiple heterogeneous files."""
    if not title.strip() or not files:
        raise BadRequestError("资产标题和至少一个文件不能为空")
    if asset_type not in AssetType.values():
        raise BadRequestError("资产类型不在受控词表中")
    try:
        manifest = json.loads(manifest_json)
    except json.JSONDecodeError as exc:
        raise BadRequestError("文件角色清单不是有效JSON") from exc
    if not isinstance(manifest, list) or len(manifest) != len(files):
        raise BadRequestError("文件角色清单必须与上传文件一一对应")

    prepared: list[tuple[UploadFile, bytes, dict, str]] = []
    metadata_extensions = {".ai", ".zip", ".rar", ".7z"}
    structured_extensions = {".pdf", ".docx", ".xlsx", ".xls", ".txt", ".pptx", ".ofd"}
    for index, upload in enumerate(files):
        item = manifest[index] if isinstance(manifest[index], dict) else {}
        role = str(item.get("role") or "reference")
        if role not in DocumentRole.values():
            raise BadRequestError(f"第{index + 1}个文件角色不在受控词表中")
        data = await upload.read()
        extension = Path(upload.filename or "").suffix.lower()
        if extension not in metadata_extensions | structured_extensions:
            raise BadRequestError(f"不支持文件格式：{extension or '无扩展名'}")
        if extension in {".pdf", ".docx", ".xlsx", ".xls", ".txt"}:
            readability = inspect_machine_readability(upload.filename or "", data)
            if not readability["accepted"]:
                raise BadRequestError(f"{upload.filename}：{readability['message']}")
        if extension in metadata_extensions and role not in {
            DocumentRole.RAW_ASSET.value,
            DocumentRole.REFERENCE.value,
        }:
            raise BadRequestError(f"{upload.filename}只能作为原始素材或参考资料")
        disposition = (
            ParseDisposition.METADATA_ONLY.value
            if extension in metadata_extensions
            else ParseDisposition.STRUCTURED.value
        )
        prepared.append((upload, data, item, disposition))

    org = await db.get(OrgUnit, actor.org_id) if actor.org_id else None
    asset = KnowledgeAsset(
        asset_type=asset_type,
        title=title.strip(),
        business_code=business_code.strip(),
        domain=domain.strip(),
        secret_level="internal",
        status="active",
        org_path=org.path if org else "/",
        governance_metadata={"created_by": actor.user_id, "source": "multi_file_upload"},
    )
    if not domain.strip() or not (await db.execute(select(source_permission(*ctx, asset, {"domain": domain.strip()})))).scalar_one():
        raise BadRequestError("该业务领域不在你的资料维护权限范围中")
    db.add(asset)
    await db.flush()
    version = AssetVersion(
        asset_id=asset.asset_id,
        version_label=version_label.strip() or "v1",
        release_state="draft",
        ingestion_state="pending",
        issue_no=business_code.strip(),
        version_metadata={"created_by": actor.user_id},
    )
    db.add(version)
    await db.flush()
    store = get_object_store()
    document_ids: list[str] = []
    for index, (upload, data, item, disposition) in enumerate(prepared):
        digest = hashlib.sha256(data).hexdigest()
        existing_document = (await db.execute(
            select(AssetDocument).where(AssetDocument.sha256 == digest)
        )).scalars().first()
        if existing_document is None:
            object_key = store.put_object(
                f"{gen_id('obj')}_{upload.filename}",
                data,
                upload.content_type or "application/octet-stream",
            )
        else:
            object_key = existing_document.object_key
        # Share immutable stored bytes, never another version's mutable
        # document identity or current parse pointer.
        document = AssetDocument(
            filename=upload.filename or f"file-{index + 1}",
            title=Path(upload.filename or f"file-{index + 1}").stem,
            mime=upload.content_type or "application/octet-stream",
            object_key=object_key, sha256=digest, size_bytes=len(data),
            parse_disposition=disposition,
        )
        db.add(document)
        await db.flush()
        db.add(AssetVersionDocument(
            version_id=version.version_id,
            document_id=document.document_id,
            role=str(item.get("role") or "reference"),
            sort_order=index,
            mandatory=bool(item.get("mandatory", True)),
            normative=bool(item.get("normative", False)),
        ))
        document_ids.append(document.document_id)
    await record_audit(db, actor_id=actor.user_id, action="asset.create", target_type="asset_version", target_id=version.version_id)
    await db.commit()
    return ok({
        "asset_id": asset.asset_id,
        "version_id": version.version_id,
        "document_ids": document_ids,
        "ingestion_state": version.ingestion_state,
    })


class AssetMetadataIn(BaseModel):
    issue_no: str | None = Field(None, max_length=96)
    issuer: str | None = Field(None, max_length=255)
    effective_date: date | None = None
    expiry_date: date | None = None
    owner_org: str | None = None
    domain: str | None = Field(None, max_length=64)
    evidence_note: str = Field(..., min_length=1, max_length=1000)


class AssetRoleIn(BaseModel):
    role: str
    mandatory: bool
    normative: bool
    evidence_note: str = Field(..., min_length=1, max_length=1000)


class AssetReviewIn(BaseModel):
    decision: str
    note: str = Field(..., min_length=1, max_length=512)


class AssetRevisionIn(BaseModel):
    version_label: str = Field(..., min_length=1, max_length=48)


class AssetConfirmationIn(BaseModel):
    note: str = Field(..., min_length=1, max_length=1000)


class AssetBatchConfirmationIn(AssetConfirmationIn):
    version_ids: list[str] = Field(..., min_length=1, max_length=2000)


async def _apply_current_version(db, version, asset, actor, ctx):
    if version.supersedes_version_id:
        previous, previous_asset = await visible_version(db, version.supersedes_version_id, *ctx)
        if previous_asset.asset_id != asset.asset_id or previous.release_state != "current":
            raise BadRequestError("被替代版本已变化，请重新核对替代关系")
        previous.release_state = "replaced"
        from app.services.assets.impact import retire_asset_rules_and_notify
        notice = await retire_asset_rules_and_notify(db, previous.version_id, version.version_id, actor.user_id)
        version.version_metadata = {**(version.version_metadata or {}), "replacement_notice": notice}
    fields = source_fields(asset, version)
    asset.owner_org, asset.domain = fields["owner_org"], fields["domain"]


async def _confirm_and_activate(db, version, asset, actor, ctx, note):
    if version.release_state not in {"draft", "rejected", "pending_review", "current"}:
        raise BadRequestError("仅草稿、待审核或现行版本可以确认来源；历史版本请保留原记录")
    if version.ingestion_state != "ready":
        raise BadRequestError("请先完成资料内容处理后再确认启用")
    if version.effective_date and version.effective_date > date.today():
        raise BadRequestError("此资料已注明未来生效日期，请在生效日启用")
    report = await publication_report(db, version, asset, *ctx, require_authority=False)
    if not report["publishable"]:
        raise BadRequestError("资料原件尚未达到可用条件", report)
    previous_state = version.release_state
    stamp_source_confirmation(version, report, actor, note)
    changed = await db.execute(update(AssetVersion).where(
        AssetVersion.version_id == version.version_id, AssetVersion.release_state == previous_state,
        AssetVersion.ingestion_state == "ready",
    ).values(release_state="current", version_metadata=version.version_metadata))
    if changed.rowcount != 1:
        raise BadRequestError("资料状态已改变，请刷新后重试")
    if previous_state != "current":
        # Maintainer confirmation is recorded separately from formal review.
        version.reviewed_by = version.reviewed_at = version.review_note = None
        await _apply_current_version(db, version, asset, actor, ctx)
    await record_audit(db, actor_id=actor.user_id, action="asset.source_confirmation", target_type="asset_version",
                       target_id=version.version_id, detail=f"kind=maintainer;{note.strip()}")


@router.post("/source-confirmations", response_model=None)
async def confirm_asset_sources(
    body: AssetBatchConfirmationIn, actor: User = Depends(require_roles("R3", "R4")),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db),
):
    if not body.note.strip():
        raise BadRequestError("请填写本人确认来源可靠的说明")
    ids = list(dict.fromkeys(body.version_ids))
    for version_id in ids:
        version, asset = await visible_version(db, version_id, *ctx)
        await _confirm_and_activate(db, version, asset, actor, ctx, body.note)
    await db.commit()
    from app.services.rag.retriever import reset_compound_vector_cache
    reset_compound_vector_cache()
    return ok({"count": len(ids), "version_ids": ids, "source_verification": "maintainer"})


@router.post("/versions/{version_id}/activate", response_model=None)
async def activate_asset_version(
    version_id: str, body: AssetConfirmationIn, actor: User = Depends(require_roles("R3", "R4")),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db),
):
    if not body.note.strip():
        raise BadRequestError("请填写本人确认来源可靠的说明")
    version, asset = await visible_version(db, version_id, *ctx)
    await _confirm_and_activate(db, version, asset, actor, ctx, body.note)
    await db.commit()
    from app.services.rag.retriever import reset_compound_vector_cache
    reset_compound_vector_cache()
    return ok({"version_id": version_id, "release_state": "current", "source_verification": "maintainer"})


@router.get("/reviews/pending", response_model=None)
async def pending_asset_reviews(
    _: User = Depends(require_roles("R2", "R4")),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db),
):
    user, permissions = ctx
    rows = (await db.execute(
        select(AssetVersion, KnowledgeAsset).join(KnowledgeAsset)
        .where(AssetVersion.release_state == "pending_review", version_filter(user, permissions))
        .order_by(AssetVersion.updated_at)
    )).all()
    return ok([{
        **_asset_payload(asset), "version_id": version.version_id,
        "version_label": version.version_label, "issue_no": version.issue_no,
        "effective_date": version.effective_date.isoformat() if version.effective_date else None,
        "ingestion_state": version.ingestion_state,
    } for version, asset in rows])


@router.patch("/versions/{version_id}/metadata", response_model=None)
async def update_asset_metadata(
    version_id: str, body: AssetMetadataIn,
    actor: User = Depends(require_roles("R3", "R4")),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db),
):
    version, asset = await visible_version(db, version_id, *ctx)
    require_editable(version)
    if not body.evidence_note.strip():
        raise BadRequestError("请填写正式原文或业务确认依据")
    data = body.model_dump(exclude_unset=True)
    for key in ("issue_no", "issuer", "effective_date", "expiry_date"):
        if key in data:
            value = data[key]
            if key in {"issue_no", "issuer"} and value is None:
                value = ""
            setattr(version, key, value.strip() if isinstance(value, str) else value)
    fields = source_fields(asset, version)
    if "owner_org" in data:
        if body.owner_org and await db.get(OrgUnit, body.owner_org) is None:
            raise BadRequestError("责任部门不在组织主数据中")
        fields["owner_org"] = body.owner_org
    if "domain" in data:
        if not body.domain or not body.domain.strip():
            raise BadRequestError("业务领域不能为空")
        fields["domain"] = body.domain.strip()
    await db.flush()
    if not (await db.execute(select(source_permission(*ctx, asset, fields)))).scalar_one():
        raise BadRequestError("该业务领域不在你的资料维护权限范围中")
    if version.expiry_date and version.effective_date and version.expiry_date < version.effective_date:
        raise BadRequestError("失效日期不能早于生效日期")
    # Draft edits must not change the live asset's authority or domain scope.
    invalidate_source_confirmation(version)
    version.version_metadata = {**(version.version_metadata or {}), "source_fields": fields, "authority_confirmation": {
        "actor_id": actor.user_id, "evidence_note": body.evidence_note.strip(),
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }}
    await record_audit(db, actor_id=actor.user_id, action="asset.metadata", target_type="asset_version",
                       target_id=version_id, detail=body.evidence_note.strip())
    await db.commit()
    return ok({"version_id": version_id, "authority_gaps": authority_gaps(asset, version)})


@router.patch("/versions/{version_id}/documents/{document_id}/role", response_model=None)
async def update_document_role(
    version_id: str, document_id: str, body: AssetRoleIn,
    actor: User = Depends(require_roles("R3", "R4")),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db),
):
    version, _asset = await visible_version(db, version_id, *ctx)
    require_editable(version)
    await visible_document(db, document_id, *ctx)
    link = (await db.execute(select(AssetVersionDocument).where(
        AssetVersionDocument.version_id == version_id, AssetVersionDocument.document_id == document_id,
    ))).scalar_one_or_none()
    if link is None:
        raise NotFoundError("该文件不属于此资料版本")
    if body.role not in DocumentRole.values() or not body.evidence_note.strip():
        raise BadRequestError("请核对文件用途并填写依据")
    link.role, link.mandatory, link.normative = body.role, body.mandatory, body.normative
    invalidate_source_confirmation(version)
    await record_audit(db, actor_id=actor.user_id, action="asset.document_role", target_type="asset_version",
                       target_id=version_id, detail=f"document={document_id};role={body.role};{body.evidence_note.strip()}")
    await db.commit()
    return ok({"version_id": version_id, "document_id": document_id})


@router.post("/versions/{version_id}/revision", response_model=None)
async def create_asset_revision(
    version_id: str, body: AssetRevisionIn,
    actor: User = Depends(require_roles("R3", "R4")),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db),
):
    source, asset = await visible_version(db, version_id, *ctx)
    label = body.version_label.strip()
    if source.release_state != "current" or not label:
        raise BadRequestError("请从已发布版本建立修订稿并填写新版本名称")
    if (await db.execute(select(AssetVersion.version_id).where(
        AssetVersion.asset_id == asset.asset_id, AssetVersion.version_label == label,
    ))).first():
        raise BadRequestError("此资料版本名称已存在")
    candidate = AssetVersion(asset_id=asset.asset_id, version_label=label, release_state="draft",
        ingestion_state="pending", effective_date=source.effective_date, expiry_date=source.expiry_date,
        issuer=source.issuer, issue_no=source.issue_no, supersedes_version_id=source.version_id,
        version_metadata={"created_by": actor.user_id, "revision_of": source.version_id})
    db.add(candidate)
    await db.flush()
    rows = (await db.execute(select(AssetVersionDocument, AssetDocument)
        .join(AssetDocument).where(AssetVersionDocument.version_id == source.version_id))).all()
    for link, document in rows:
        # A revision owns separate physical-document identities so processing
        # it cannot switch the live version's current parse snapshot.
        copied = AssetDocument(filename=document.filename, title=document.title, mime=document.mime,
            object_key=document.object_key, sha256=document.sha256, size_bytes=document.size_bytes,
            source_path=document.source_path, secret_level=document.secret_level,
            parse_disposition=document.parse_disposition, document_metadata=dict(document.document_metadata or {}))
        db.add(copied)
        await db.flush()
        db.add(AssetVersionDocument(version_id=candidate.version_id, document_id=copied.document_id,
            role=link.role, sort_order=link.sort_order, mandatory=link.mandatory, normative=link.normative))
    await record_audit(db, actor_id=actor.user_id, action="asset.revision", target_type="asset_version", target_id=candidate.version_id)
    await db.commit()
    return ok({"asset_id": asset.asset_id, "version_id": candidate.version_id})


@router.post("/versions/{version_id}/submit", response_model=None)
async def submit_asset_version(
    version_id: str, actor: User = Depends(require_roles("R3", "R4")),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db),
):
    version, asset = await visible_version(db, version_id, *ctx)
    require_editable(version)
    report = await publication_report(db, version, asset, *ctx)
    if not report["publishable"]:
        raise BadRequestError("资料未达到提交审核条件", report)
    metadata = {**(version.version_metadata or {}), "submission": {
        "actor_id": actor.user_id, "submitted_at": datetime.now(timezone.utc).isoformat(),
        "fingerprint": report["fingerprint"],
    }}
    changed = await db.execute(update(AssetVersion).where(
        AssetVersion.version_id == version_id, AssetVersion.release_state.in_(["draft", "rejected"]),
    ).values(release_state="pending_review", ingestion_state="ready", version_metadata=metadata,
             reviewed_by=None, reviewed_at=None, review_note=None))
    if changed.rowcount != 1:
        raise BadRequestError("资料状态已改变，请刷新后重试")
    await record_audit(db, actor_id=actor.user_id, action="asset.submit", target_type="asset_version", target_id=version_id)
    await db.commit()
    return ok({"version_id": version_id, "release_state": "pending_review"})


@router.post("/versions/{version_id}/review", response_model=None)
async def review_asset_version(
    version_id: str, body: AssetReviewIn,
    actor: User = Depends(require_roles("R2", "R4")),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db),
):
    version, asset = await visible_version(db, version_id, *ctx)
    if version.release_state != "pending_review":
        raise BadRequestError("资料已不在待审核状态，请刷新队列")
    if body.decision not in {"approve", "reject"} or not body.note.strip():
        raise BadRequestError("请选择审核决定并填写核对意见")
    if body.decision == "approve":
        report = await publication_report(db, version, asset, *ctx)
        submitted = (version.version_metadata or {}).get("submission", {}).get("fingerprint")
        if not report["publishable"] or not submitted or submitted != report["fingerprint"]:
            raise BadRequestError("资料或原文状态已变化，请退回修正后重新提交", report)
        if version.supersedes_version_id and version.effective_date > date.today():
            raise BadRequestError("替代版本尚未生效，请在生效日完成发布")
    state = "current" if body.decision == "approve" else "rejected"
    changed = await db.execute(update(AssetVersion).where(
        AssetVersion.version_id == version_id, AssetVersion.release_state == "pending_review",
    ).values(release_state=state, reviewed_by=actor.user_id,
             reviewed_at=datetime.now(timezone.utc), review_note=body.note.strip()))
    if changed.rowcount != 1:
        raise BadRequestError("资料已被其他审核人员处理，请刷新")
    if state == "current":
        await _apply_current_version(db, version, asset, actor, ctx)
    await record_audit(db, actor_id=actor.user_id, action="asset.review", target_type="asset_version",
                       target_id=version_id, detail=f"decision={body.decision};{body.note.strip()}")
    await db.commit()
    from app.services.rag.retriever import reset_compound_vector_cache
    reset_compound_vector_cache()
    return ok({"version_id": version_id, "release_state": state})


@router.get("/{asset_id}", response_model=None)
async def asset_detail(
    asset_id: str,
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, permissions = ctx
    asset = (await db.execute(select(KnowledgeAsset).where(
        KnowledgeAsset.asset_id == asset_id, KnowledgeAsset.status == "active", asset_filter(user, permissions),
    ))).scalar_one_or_none()
    if asset is None:
        raise NotFoundError("治理资产不存在")
    versions = list((await db.execute(
        select(AssetVersion).join(KnowledgeAsset).where(
            AssetVersion.asset_id == asset_id, version_filter(user, permissions),
        ).order_by(AssetVersion.created_at.desc())
    )).scalars())
    if not versions:
        raise NotFoundError("资料不存在或当前不可见")
    result = []
    for version in versions:
        fields = source_fields(asset, version)
        activation_gate = await publication_report(db, version, asset, user, permissions, require_authority=False)
        verification = source_verification(asset, version, report=activation_gate)
        owner = await db.get(OrgUnit, fields["owner_org"]) if fields["owner_org"] else None
        rows = (await db.execute(
            select(AssetVersionDocument, AssetDocument, DocumentParseRun)
            .join(AssetDocument, AssetDocument.document_id == AssetVersionDocument.document_id)
            .outerjoin(
                DocumentParseRun,
                (DocumentParseRun.document_id == AssetDocument.document_id)
                & (DocumentParseRun.is_current.is_(True)),
            )
            .join(AssetVersion, AssetVersion.version_id == AssetVersionDocument.version_id)
            .join(KnowledgeAsset, KnowledgeAsset.asset_id == AssetVersion.asset_id)
            .where(AssetVersionDocument.version_id == version.version_id, asset_filter(user, permissions, document=True))
            .order_by(AssetVersionDocument.sort_order)
        )).all()
        result.append({
            "version_id": version.version_id,
            "version_label": version.version_label,
            "release_state": version.release_state,
            "ingestion_state": version.ingestion_state,
            "issue_no": version.issue_no,
            "issuer": version.issuer,
            **fields,
            "owner_org_name": owner.name if owner else None,
            "replacement_notice": (version.version_metadata or {}).get("replacement_notice"),
            "effective_date": version.effective_date.isoformat() if version.effective_date else None,
            "expiry_date": version.expiry_date.isoformat() if version.expiry_date else None,
            "authority_gaps": authority_gaps(asset, version),
            "source_verification": verification,
            "authority_verified": version.release_state == "current" and version.ingestion_state == "ready"
                and (version.effective_date is None or version.effective_date <= date.today())
                and (version.expiry_date is None or version.expiry_date >= date.today()) and verification != "unconfirmed",
            "source_confirmation": (version.version_metadata or {}).get("source_confirmation") if user.role in {"R3", "R4"} else None,
            "review_note": version.review_note,
            "reviewed_at": version.reviewed_at.isoformat() if version.reviewed_at else None,
            "publication_gate": await publication_report(db, version, asset, user, permissions) if user.role != "R1" else None,
            "activation_gate": activation_gate if user.role in {"R3", "R4"} else None,
            "documents": [
                {
                    "document_id": document.document_id,
                    "filename": document.filename,
                    "title": document.title,
                    "role": link.role,
                    "mandatory": link.mandatory,
                    "normative": link.normative,
                    "parse_disposition": document.parse_disposition,
                    "size_bytes": document.size_bytes,
                    "parse_run_id": run.parse_run_id if run else None,
                    "parse_status": run.status if run else "pending",
                    "quality_report": run.quality_report if run else {},
                }
                for link, document, run in rows
            ],
        })
    return ok({**_asset_payload(asset), "versions": result})


@router.get("/versions/{version_id}/reading", response_model=None)
async def read_asset_version(
    version_id: str, keyword: str | None = None,
    offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200),
    ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db),
):
    user, permissions = ctx
    version, asset = await visible_version(db, version_id, *ctx)
    if (version.release_state != "current" or version.ingestion_state != "ready"
        or (version.effective_date and version.effective_date > date.today())
        or (version.expiry_date and version.expiry_date < date.today())):
        raise NotFoundError("资料尚未发布或不在有效阅读期间")
    stmt = (select(RetrievalUnit, ContentNode, AssetDocument)
        .join(AssetVersion, AssetVersion.version_id == RetrievalUnit.version_id)
        .join(KnowledgeAsset, KnowledgeAsset.asset_id == AssetVersion.asset_id)
        .join(RetrievalUnitSource, RetrievalUnitSource.unit_id == RetrievalUnit.unit_id)
        .join(ContentNode, ContentNode.node_id == RetrievalUnitSource.node_id)
        .join(DocumentParseRun, DocumentParseRun.parse_run_id == ContentNode.parse_run_id)
        .join(AssetDocument, AssetDocument.document_id == ContentNode.document_id)
        .join(AssetVersionDocument, (AssetVersionDocument.version_id == AssetVersion.version_id)
              & (AssetVersionDocument.document_id == AssetDocument.document_id))
        .where(RetrievalUnit.version_id == version_id, *eligible_unit_predicates(),
            asset_filter(user, permissions, document=True),
            build_asset_filter(user, permissions, secret_level=KnowledgeAsset.secret_level,
                org_path=KnowledgeAsset.org_path, domain=KnowledgeAsset.domain,
                content_secret_level=RetrievalUnit.secret_level)))
    if keyword and keyword.strip():
        stmt = stmt.where(RetrievalUnit.text.contains(keyword.strip(), autoescape=True))
    ids = stmt.with_only_columns(RetrievalUnit.unit_id,
        func.min(AssetVersionDocument.sort_order).label("document_order"),
        func.min(ContentNode.order_path).label("node_order")).group_by(RetrievalUnit.unit_id).subquery()
    total = int((await db.execute(select(func.count()).select_from(ids))).scalar_one())
    page_ids = list((await db.execute(select(ids.c.unit_id).order_by(ids.c.document_order, ids.c.node_order, ids.c.unit_id).offset(offset).limit(limit))).scalars())
    if not page_ids:
        return ok({"clauses": [], "total": total})
    rows = (await db.execute(stmt.where(RetrievalUnit.unit_id.in_(page_ids))
        .order_by(AssetVersionDocument.sort_order, ContentNode.order_path, RetrievalUnitSource.sequence))).all()
    clauses = {}
    for unit, node, document in rows:
        clauses.setdefault(unit.unit_id, {"clause_id": unit.unit_id, "file_id": asset.asset_id,
            "chapter": document.title or document.filename, "clause_no": unit.title,
            "content": unit.text, "source_page": node.source_page,
            "source_locator": node.source_locator, "content_hash": unit.content_hash})
    return ok({"clauses": list(clauses.values()), "total": total})


@router.get("/versions/{version_id}/documents/{document_id}/download", response_model=None)
async def download_asset_document(
    version_id: str, document_id: str, ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    document = (await db.execute(select(AssetDocument)
        .join(AssetVersionDocument, AssetVersionDocument.document_id == AssetDocument.document_id)
        .join(AssetVersion, AssetVersion.version_id == AssetVersionDocument.version_id)
        .join(KnowledgeAsset, KnowledgeAsset.asset_id == AssetVersion.asset_id)
        .where(AssetVersion.version_id == version_id, AssetDocument.document_id == document_id,
               version_filter(*ctx, document=True)))).scalar_one_or_none()
    if document is None:
        raise NotFoundError("资料原件不存在或无权限")
    data = await asyncio.to_thread(lambda: get_object_store().get_object(document.object_key))
    if data is None:
        raise NotFoundError("原件未找到，请联系资料管理员")
    name = Path(document.filename.replace("\\", "/")).name
    suffix = Path(name).suffix
    return StreamingResponse(iter([data]), media_type=document.mime or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={document.document_id}{suffix}; filename*=UTF-8''{quote(name)}"})


@router.get("/documents/{document_id}/tree", response_model=None)
async def document_tree(
    document_id: str,
    parse_run_id: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(300, ge=1, le=1000),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    document = await visible_document(db, document_id, *ctx)
    if not parse_run_id:
        parse_run_id = (await db.execute(
            select(DocumentParseRun.parse_run_id).where(
                DocumentParseRun.document_id == document_id,
                DocumentParseRun.is_current.is_(True),
            )
        )).scalar_one_or_none()
    if not parse_run_id:
        return ok({
            "document_id": document_id,
            "filename": document.filename,
            "total": 0,
            "offset": offset,
            "limit": limit,
            "nodes": [],
        })
    run = await db.get(DocumentParseRun, parse_run_id)
    if run is None or run.document_id != document_id or (ctx[0].role == "R1" and (not run.is_current or run.status != "succeeded")):
        raise NotFoundError("文件处理快照不存在或无权限")
    total = int((await db.execute(
        select(func.count()).select_from(ContentNode).where(ContentNode.parse_run_id == parse_run_id)
    )).scalar_one())
    nodes = list((await db.execute(
        select(ContentNode)
        .where(ContentNode.parse_run_id == parse_run_id)
        .order_by(ContentNode.order_path)
        .offset(offset)
        .limit(limit)
    )).scalars())
    return ok({
        "document_id": document_id,
        "filename": document.filename,
        "parse_run_id": parse_run_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "nodes": [
            {
                "node_id": node.node_id,
                "parent_id": node.parent_id,
                "node_type": node.node_type,
                "order_path": node.order_path,
                "label": node.label,
                "title": node.title,
                "text": node.text,
                "source_page": node.source_page,
                "source_locator": node.source_locator,
                "sheet_name": node.sheet_name,
                "cell_range": node.cell_range,
                "structure": node.structure,
                "is_citable": node.is_citable,
            }
            for node in nodes
        ],
    })


@router.post("/documents/{document_id}/parse", response_model=None)
async def parse_document(
    document_id: str,
    _: object = Depends(require_roles("R3", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    await visible_document(db, document_id, *ctx)
    versions = (await db.execute(select(AssetVersion).join(AssetVersionDocument)
        .where(AssetVersionDocument.document_id == document_id))).scalars().all()
    for version in versions:
        require_editable(version)
        invalidate_source_confirmation(version)
    try:
        result = await parse_asset_document(db, document_id)
        await db.commit()
        return ok(result)
    except ValueError as exc:
        await db.rollback()
        raise BadRequestError(str(exc)) from exc


@router.post("/versions/{version_id}/parse", response_model=None)
async def parse_version_documents(
    version_id: str,
    _: object = Depends(require_roles("R3", "R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    version, _asset = await visible_version(db, version_id, *ctx)
    require_editable(version)
    invalidate_source_confirmation(version)
    document_ids = list((await db.execute(
        select(AssetVersionDocument.document_id)
        .where(AssetVersionDocument.version_id == version_id)
        .order_by(AssetVersionDocument.sort_order)
    )).scalars())
    results = []
    for document_id in document_ids:
        await visible_document(db, document_id, *ctx)
        try:
            results.append(await parse_asset_document(db, document_id))
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - preserve per-file progress and evidence
            await db.commit()
            results.append({"document_id": document_id, "status": "failed", "error": str(exc)[:200]})
    await db.refresh(version)
    return ok({"version_id": version_id, "ingestion_state": version.ingestion_state, "documents": results})


@router.post("/migration/benchmarks", response_model=None)
async def migrate_benchmarks(
    dry_run: bool = Query(True),
    actor: User = Depends(require_roles("R4")),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    rows = list((await db.execute(
        select(RegulationFile).where(RegulationFile.title.in_(BENCHMARK_TITLES), build_filter(*ctx))
    )).scalars())
    found = {row.title for row in rows}
    missing = [title for title in BENCHMARK_TITLES if title not in found]
    if dry_run:
        return ok({
            "dry_run": True,
            "requested": len(BENCHMARK_TITLES),
            "found": len(rows),
            "missing": missing,
            "legacy_file_ids": [row.file_id for row in rows],
        })
    version_ids: list[str] = []
    for row in rows:
        version_ids.extend(await migrate_legacy_regulation(db, row.file_id))
    await db.commit()
    return ok({
        "dry_run": False,
        "requested": len(BENCHMARK_TITLES),
        "found": len(rows),
        "missing": missing,
        "version_ids": version_ids,
        "migrated_by": actor.user_id,
        "migrated_at": datetime.now(timezone.utc).isoformat(),
    })
