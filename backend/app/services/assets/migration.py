"""Non-destructive migration from V1 regulation records to compound assets."""
from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.storage.object_store import get_object_store
from app.db.models.asset import (
    AssetDocument,
    AssetVersion,
    AssetVersionDocument,
    KnowledgeAsset,
    LegacyAssetMapping,
    ReleaseEvent,
)
from app.db.models.regulation import RegulationFile
from app.db.models.regulation_document import RegulationDocument
from app.services.assets.benchmark_manifest import SPECIAL_SPLIT_PACKAGES, SplitAssetSpec
from app.services.assets.taxonomy import AssetType, DocumentRole, ParseDisposition


def infer_asset_type(title: str) -> str:
    name = title or ""
    if "汇编" in name:
        return AssetType.COMPILATION.value
    if "模板" in name:
        return AssetType.TEMPLATE_PACKAGE.value
    if "视觉识别" in name or "资源" in name:
        return AssetType.RESOURCE_PACKAGE.value
    if "清单" in name or "目录" in name:
        return AssetType.CHECKLIST.value
    if "手册" in name:
        return AssetType.MANUAL.value
    if "指引" in name or "指南" in name:
        return AssetType.GUIDELINE.value
    if "细则" in name:
        return AssetType.IMPLEMENTATION_RULE.value
    if "办法" in name:
        return AssetType.MANAGEMENT_METHOD.value
    if "标准" in name or "规范" in name:
        return AssetType.STANDARD.value
    return AssetType.REGULATION.value


def infer_document_role(document: RegulationDocument) -> str:
    filename = document.filename or document.title or ""
    extension = Path(filename).suffix.lower()
    if document.doc_type == "history":
        return DocumentRole.HISTORY.value
    if document.doc_type == "review_opinion":
        return DocumentRole.REVIEW_OPINION.value
    if document.doc_type == "training":
        return DocumentRole.TRAINING.value
    if extension in {".ai", ".zip", ".rar", ".7z"}:
        return DocumentRole.RAW_ASSET.value
    if "通知" in filename and ("印发" in filename or "关于" in filename):
        return DocumentRole.ISSUANCE_NOTICE.value
    if "编制说明" in filename:
        return DocumentRole.DRAFTING_NOTE.value
    if "流程图" in filename or "流程" in filename and extension in {".png", ".jpg", ".jpeg"}:
        return DocumentRole.FLOWCHART.value
    if "模板" in filename:
        return DocumentRole.TEMPLATE.value
    if any(word in filename for word in ("申报表", "评审表", "一览表", "申请表", "记录表")):
        return DocumentRole.FORM.value
    if extension in {".xlsx", ".xls"} and any(word in filename for word in ("标准", "清单", "权限", "目录", "测算")):
        return DocumentRole.STANDARD_TABLE.value
    if document.doc_type == "main":
        return DocumentRole.NORMATIVE_BODY.value
    return DocumentRole.NORMATIVE_ANNEX.value


def _disposition(filename: str) -> tuple[str, str | None]:
    extension = Path(filename).suffix.lower()
    if extension in {".ai", ".zip", ".rar", ".7z"}:
        return ParseDisposition.METADATA_ONLY.value, "原始设计或压缩素材按文件资产保存"
    if extension in {".docx", ".doc", ".pdf", ".xlsx", ".xls", ".pptx", ".ofd", ".txt"}:
        return ParseDisposition.STRUCTURED.value, None
    return ParseDisposition.METADATA_ONLY.value, f"当前未配置{extension or '无扩展名'}结构解析器"


async def _get_or_create_document(
    session: AsyncSession,
    legacy: RegulationDocument,
    secret_level: str,
) -> AssetDocument:
    source = get_object_store().get_object(legacy.object_key or "") if legacy.object_key else None
    if source is None:
        raise ValueError(f"原始文件不可读取：{legacy.doc_id}")
    digest = hashlib.sha256(source).hexdigest()
    existing = (
        await session.execute(select(AssetDocument).where(AssetDocument.sha256 == digest))
    ).scalars().first()
    if existing is not None:
        return existing
    disposition, reason = _disposition(legacy.filename)
    document = AssetDocument(
        filename=legacy.filename,
        title=legacy.title,
        mime=legacy.mime,
        object_key=legacy.object_key or "",
        sha256=digest,
        size_bytes=len(source),
        source_path=legacy.source_path,
        secret_level=secret_level,
        parse_disposition=disposition,
        disposition_reason=reason,
        document_metadata={"legacy_doc_id": legacy.doc_id, "legacy_doc_type": legacy.doc_type},
    )
    session.add(document)
    await session.flush()
    session.add(LegacyAssetMapping(
        legacy_type="regulation_document",
        legacy_id=legacy.doc_id,
        target_type="asset_document",
        target_id=document.document_id,
        mapping_status="verified",
    ))
    return document


async def _create_version(
    session: AsyncSession,
    regulation: RegulationFile,
    title: str,
    asset_type: str,
    release_event_id: str | None,
) -> tuple[KnowledgeAsset, AssetVersion]:
    asset = KnowledgeAsset(
        asset_type=asset_type,
        title=title,
        business_code=regulation.regulation_code,
        owner_org=regulation.owner_org,
        org_path=regulation.org_path,
        secret_level=regulation.secret_level,
        domain=regulation.domain,
        lang=regulation.lang,
        status="active",
        governance_metadata={"migration_source": "v1"},
    )
    session.add(asset)
    await session.flush()
    version = AssetVersion(
        asset_id=asset.asset_id,
        release_event_id=release_event_id,
        version_label=regulation.version,
        release_state="current" if regulation.status == "current" else regulation.status,
        ingestion_state="pending",
        effective_date=regulation.effective_date,
        expiry_date=regulation.expiry_date,
        issue_no=regulation.regulation_code,
        legacy_file_id=regulation.file_id,
    )
    session.add(version)
    await session.flush()
    for target_type, target_id in (("knowledge_asset", asset.asset_id), ("asset_version", version.version_id)):
        session.add(LegacyAssetMapping(
            legacy_type="regulation_file",
            legacy_id=regulation.file_id,
            target_type=target_type,
            target_id=target_id,
            mapping_status="verified" if title == regulation.title else "reviewed_split",
        ))
    return asset, version


async def _link_document(
    session: AsyncSession,
    version: AssetVersion,
    document: AssetDocument,
    role: str,
    order: int,
) -> None:
    exists = (
        await session.execute(
            select(AssetVersionDocument.link_id).where(
                AssetVersionDocument.version_id == version.version_id,
                AssetVersionDocument.document_id == document.document_id,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        return
    session.add(AssetVersionDocument(
        version_id=version.version_id,
        document_id=document.document_id,
        role=role,
        sort_order=order,
        mandatory=role not in {
            DocumentRole.HISTORY.value,
            DocumentRole.REVIEW_OPINION.value,
            DocumentRole.TRAINING.value,
            DocumentRole.RAW_ASSET.value,
        },
        normative=role in {
            DocumentRole.NORMATIVE_BODY.value,
            DocumentRole.NORMATIVE_ANNEX.value,
            DocumentRole.STANDARD_TABLE.value,
        },
    ))


def _matches_spec(document: RegulationDocument, spec: SplitAssetSpec) -> bool:
    filename = document.filename or ""
    return spec.body_filename_contains in filename or any(
        text in filename for text in spec.extra_filename_contains
    )


async def migrate_legacy_regulation(session: AsyncSession, file_id: str) -> list[str]:
    already = (
        await session.execute(
            select(LegacyAssetMapping.target_id).where(
                LegacyAssetMapping.legacy_type == "regulation_file",
                LegacyAssetMapping.legacy_id == file_id,
                LegacyAssetMapping.target_type == "asset_version",
            )
        )
    ).scalars().all()
    if already:
        return list(already)
    regulation = await session.get(RegulationFile, file_id)
    if regulation is None:
        raise ValueError("旧制度不存在")
    legacy_documents = list((await session.execute(
        select(RegulationDocument)
        .where(RegulationDocument.file_id == file_id)
        .order_by(RegulationDocument.sort_order, RegulationDocument.doc_id)
    )).scalars())
    release_event = None
    if any(infer_document_role(item) == DocumentRole.ISSUANCE_NOTICE.value for item in legacy_documents):
        release_event = ReleaseEvent(
            title=f"{regulation.title}发布事件",
            issue_no=regulation.regulation_code,
            source=regulation.source,
            status="verified",
            release_metadata={"legacy_file_id": file_id},
        )
        session.add(release_event)
        await session.flush()

    migrated_documents: list[tuple[RegulationDocument, AssetDocument]] = []
    for item in legacy_documents:
        migrated_documents.append((item, await _get_or_create_document(session, item, regulation.secret_level)))

    versions: list[AssetVersion] = []
    split_specs = SPECIAL_SPLIT_PACKAGES.get(regulation.title)
    if split_specs:
        for spec in split_specs:
            _, version = await _create_version(
                session, regulation, spec.title, spec.asset_type,
                release_event.release_event_id if release_event else None,
            )
            versions.append(version)
            order = 0
            for legacy, document in migrated_documents:
                role = infer_document_role(legacy)
                if role == DocumentRole.ISSUANCE_NOTICE.value or _matches_spec(legacy, spec):
                    if spec.body_filename_contains in legacy.filename:
                        role = DocumentRole.NORMATIVE_BODY.value
                    await _link_document(session, version, document, role, order)
                    order += 1
    else:
        _, version = await _create_version(
            session, regulation, regulation.title, infer_asset_type(regulation.title),
            release_event.release_event_id if release_event else None,
        )
        versions.append(version)
        for order, (legacy, document) in enumerate(migrated_documents):
            await _link_document(session, version, document, infer_document_role(legacy), order)
    await session.flush()
    return [item.version_id for item in versions]
