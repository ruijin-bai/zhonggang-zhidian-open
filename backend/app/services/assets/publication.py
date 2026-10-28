"""Permission and publication gates for compound governance assets."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone

from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.db.models.asset import (
    AssetDocument, AssetVersion, AssetVersionDocument, ContentNode,
    DocumentParseRun, KnowledgeAsset,
)
from app.services.assets.retrieval_index import QA_DOCUMENT_ROLES
from app.services.permission.rbac import build_asset_filter
from app.services.governance_state import valid_source_confirmation


def asset_filter(user, permissions, *, document=False):
    return build_asset_filter(
        user, permissions,
        secret_level=KnowledgeAsset.secret_level,
        content_secret_level=AssetDocument.secret_level if document else None,
        org_path=KnowledgeAsset.org_path, domain=KnowledgeAsset.domain,
    )


def version_filter(user, permissions, *, document=False):
    predicates = [KnowledgeAsset.status == "active", asset_filter(user, permissions, document=document)]
    if user.role == "R1":
        # A missing source date remains unknown and does not prevent reading.
        predicates.extend([
            AssetVersion.release_state == "current", AssetVersion.ingestion_state == "ready",
            or_(AssetVersion.effective_date.is_(None), AssetVersion.effective_date <= date.today()),
            or_(AssetVersion.expiry_date.is_(None), AssetVersion.expiry_date >= date.today()),
        ])
    elif user.role == "R2":
        predicates.append(AssetVersion.release_state.in_(["pending_review", "current", "rejected", "replaced"]))
    return and_(*predicates)


async def visible_version(session: AsyncSession, version_id: str, user, permissions):
    row = (await session.execute(
        select(AssetVersion, KnowledgeAsset)
        .join(KnowledgeAsset, KnowledgeAsset.asset_id == AssetVersion.asset_id)
        .where(AssetVersion.version_id == version_id, version_filter(user, permissions))
    )).first()
    if row is None:
        raise NotFoundError("资料版本不存在或无权限")
    return row


async def visible_document(session: AsyncSession, document_id: str, user, permissions):
    document = (await session.execute(
        select(AssetDocument)
        .join(AssetVersionDocument, AssetVersionDocument.document_id == AssetDocument.document_id)
        .join(AssetVersion, AssetVersion.version_id == AssetVersionDocument.version_id)
        .join(KnowledgeAsset, KnowledgeAsset.asset_id == AssetVersion.asset_id)
        .where(AssetDocument.document_id == document_id, version_filter(user, permissions, document=True))
    )).scalars().first()
    if document is None:
        raise NotFoundError("资料文件不存在或无权限")
    return document


def require_editable(version: AssetVersion):
    if version.release_state not in {"draft", "rejected"}:
        raise BadRequestError("仅草稿或已退回版本可修改；已发布资料请先建立修订稿")


def source_fields(asset: KnowledgeAsset, version: AssetVersion) -> dict:
    pending = (version.version_metadata or {}).get("source_fields", {})
    return {"owner_org": pending.get("owner_org", asset.owner_org),
            "domain": pending.get("domain", asset.domain)}


def source_permission(user, permissions, asset, fields):
    return build_asset_filter(user, permissions, secret_level=literal(asset.secret_level),
        org_path=literal(asset.org_path), domain=literal(fields["domain"]))


def authority_gaps(asset: KnowledgeAsset, version: AssetVersion) -> list[str]:
    fields = source_fields(asset, version)
    gaps = []
    if not (version.issue_no or "").strip() or version.issue_no.strip() == asset.title.strip():
        gaps.append("issue_no")
    if version.effective_date is None:
        gaps.append("effective_date")
    if not fields["owner_org"]:
        gaps.append("owner_org")
    if not fields["domain"] or fields["domain"] == "*":
        gaps.append("domain")
    return gaps


def invalidate_source_confirmation(version: AssetVersion):
    metadata = dict(version.version_metadata or {})
    metadata.pop("source_confirmation", None)
    metadata.pop("source_manifest_fingerprint", None)
    version.version_metadata = metadata


def stamp_source_confirmation(version: AssetVersion, report: dict, actor, note: str) -> dict:
    """Bind the maintainer declaration to this version's readable originals.

    The caller must first run the permission-aware basic publication report.
    This helper does not publish, commit, or pretend that a department reviewed.
    """
    if not report.get("publishable") or not report.get("manifest_fingerprint") or not note.strip():
        raise BadRequestError("资料原件尚未可用，或来源确认说明为空")
    statement = {"kind": "maintainer", "confirmed": True, "actor_id": actor.user_id,
                 "confirmed_at": datetime.now(timezone.utc).isoformat(), "note": note.strip(),
                 "version_id": version.version_id, "manifest_fingerprint": report["manifest_fingerprint"]}
    version.version_metadata = {**(version.version_metadata or {}), "source_confirmation": statement,
                                "source_manifest_fingerprint": report["manifest_fingerprint"]}
    return statement


def source_verification(asset: KnowledgeAsset, version: AssetVersion, *, report: dict | None = None) -> str:
    metadata = version.version_metadata or {}
    statement = metadata.get("source_confirmation")
    if (valid_source_confirmation(statement)
        and statement.get("version_id") == version.version_id
        and statement.get("manifest_fingerprint")
        and statement.get("manifest_fingerprint") == metadata.get("source_manifest_fingerprint")
        and (report is None or statement.get("manifest_fingerprint") == report.get("manifest_fingerprint"))):
        return "maintainer"
    return "metadata" if not authority_gaps(asset, version) else "unconfirmed"


async def publication_report(session: AsyncSession, version: AssetVersion, asset: KnowledgeAsset, user, permissions, *, require_authority=True):
    fields = source_fields(asset, version)
    rows = (await session.execute(
        select(AssetVersionDocument, AssetDocument, DocumentParseRun)
        .join(AssetDocument, AssetDocument.document_id == AssetVersionDocument.document_id)
        .outerjoin(DocumentParseRun, and_(
            DocumentParseRun.document_id == AssetDocument.document_id,
            DocumentParseRun.is_current.is_(True),
        ))
        .where(AssetVersionDocument.version_id == version.version_id)
        .order_by(AssetVersionDocument.sort_order, AssetDocument.document_id)
    )).all()
    visible_ids = set((await session.execute(
        select(AssetDocument.document_id)
        .join(AssetVersionDocument, AssetVersionDocument.document_id == AssetDocument.document_id)
        .join(AssetVersion, AssetVersion.version_id == AssetVersionDocument.version_id)
        .join(KnowledgeAsset, KnowledgeAsset.asset_id == AssetVersion.asset_id)
        .where(AssetVersion.version_id == version.version_id, asset_filter(user, permissions, document=True))
    )).scalars())
    errors = []
    if not (await session.execute(select(source_permission(user, permissions, asset, fields)))).scalar_one():
        errors.append("拟发布业务领域不在你的资料审核权限范围中")
    gaps = authority_gaps(asset, version)
    field_names = {"issue_no": "正式文号", "effective_date": "生效日期", "owner_org": "责任部门", "domain": "业务领域"}
    if require_authority and gaps:
        errors.append("请依据正式原文核对：" + "、".join(field_names[key] for key in gaps))
    if version.expiry_date and version.effective_date and version.expiry_date < version.effective_date:
        errors.append("失效日期不得早于生效日期")
    if version.expiry_date and version.expiry_date < date.today():
        errors.append("已失效资料不能作为新版本发布")
    if not rows:
        errors.append("资料版本没有组成文件")
    citable_total = 0
    manifest = []
    for link, document, run in rows:
        required = link.mandatory or link.normative
        count = 0
        if run and run.status == "succeeded":
            count = int((await session.execute(
                select(func.count()).select_from(ContentNode).where(
                    ContentNode.parse_run_id == run.parse_run_id,
                    ContentNode.is_citable.is_(True), ContentNode.text != "",
                    or_(ContentNode.source_locator.isnot(None), ContentNode.source_page.isnot(None)),
                )
            )).scalar_one())
        # Include hidden auxiliary originals in the identity stamp without
        # disclosing their names. They cannot contribute to readable content.
        manifest.append({
            "document_id": document.document_id, "sha256": document.sha256,
            "role": link.role, "mandatory": link.mandatory, "normative": link.normative,
            "parse_run_id": run.parse_run_id if run else None,
            "source_hash": run.source_hash if run else None,
            "parse_status": run.status if run else None, "citable_count": count,
        })
        if document.document_id not in visible_ids:
            if required:
                errors.append("存在未授权的必备文件，无法完成资料核验")
            continue
        if required and run and run.status in {"failed", "requires_ocr", "needs_review"}:
            errors.append(f"{document.filename}：必备文件尚未通过完整处理")
        elif required and document.parse_disposition == "excluded":
            errors.append(f"{document.filename}：文件被拒绝入库")
        elif required and document.parse_disposition != "metadata_only":
            if not run or run.status != "succeeded" or run.source_hash != document.sha256:
                errors.append(f"{document.filename}：必备文件尚未通过完整处理")
            elif count == 0:
                errors.append(f"{document.filename}：没有可引用且有原文定位的内容")
        if link.role in QA_DOCUMENT_ROLES and document.parse_disposition == "structured":
            citable_total += count
    if citable_total == 0:
        errors.append("没有可作为现行资料依据的正文、附件或表格内容")
    manifest_fingerprint = hashlib.sha256(json.dumps({"version_id": version.version_id, "documents": manifest},
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps({
        "issue_no": version.issue_no, "issuer": version.issuer, "effective_date": str(version.effective_date),
        "expiry_date": str(version.expiry_date), "owner_org": fields["owner_org"],
        "domain": fields["domain"], "org_path": asset.org_path, "secret_level": asset.secret_level,
        "documents": manifest,
    }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {"publishable": not errors, "errors": errors, "authority_gaps": gaps,
            "citable_count": citable_total, "fingerprint": fingerprint, "manifest_fingerprint": manifest_fingerprint}
