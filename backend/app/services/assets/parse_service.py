"""Persist immutable document AST snapshots and derived citation units."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.storage.object_store import get_object_store
from app.db.base import gen_id
from app.db.models.asset import (
    AssetDocument,
    AssetVersion,
    AssetVersionDocument,
    CitationSpan,
    ContentNode,
    DocumentParseRun,
    RetrievalEmbedding,
    RetrievalUnit,
    RetrievalUnitSource,
)
from app.services.assets.document_ast import citable_nodes, flatten_ast, parse_document_ast
from app.services.assets.taxonomy import ParseDisposition, ParseRunStatus


def _normalized(value: str) -> str:
    return " ".join((value or "").split())


def _retrieval_segments(text: str, max_chars: int = 1600, overlap: int = 120) -> list[tuple[int, int, str]]:
    """Split oversized nodes into bounded, source-addressable retrieval units.

    Spreadsheet rows and long annex paragraphs can exceed an embedding model's
    input window.  Segments retain offsets into the immutable node so citations
    still resolve to exact source text instead of a generated summary.
    """
    value = text or ""
    if len(value) <= max_chars:
        return [(0, len(value), value)] if value else []
    stops = "。；;！？!?\n"
    segments: list[tuple[int, int, str]] = []
    start = 0
    while start < len(value):
        hard_end = min(len(value), start + max_chars)
        end = hard_end
        if hard_end < len(value):
            floor = start + max_chars // 2
            candidates = [value.rfind(mark, floor, hard_end) for mark in stops]
            boundary = max(candidates)
            if boundary >= floor:
                end = boundary + 1
        chunk = value[start:end].strip()
        if chunk:
            left_trim = len(value[start:end]) - len(value[start:end].lstrip())
            right_trim = len(value[start:end].rstrip())
            actual_start = start + left_trim
            actual_end = start + right_trim
            segments.append((actual_start, actual_end, value[actual_start:actual_end]))
        if end >= len(value):
            break
        start = max(end - overlap, start + 1)
    return segments


async def _isolate_retrieval_units_for_runs(
    session: AsyncSession, parse_run_ids: list[str]
) -> None:
    """Retire derived units without deleting immutable parse evidence."""
    if not parse_run_ids:
        return
    node_ids = list((await session.execute(
        select(ContentNode.node_id).where(ContentNode.parse_run_id.in_(parse_run_ids))
    )).scalars())
    if not node_ids:
        return
    unit_ids = list((await session.execute(
        select(RetrievalUnitSource.unit_id).where(RetrievalUnitSource.node_id.in_(node_ids))
    )).scalars())
    if unit_ids:
        await session.execute(
            update(RetrievalEmbedding)
            .where(RetrievalEmbedding.unit_id.in_(unit_ids))
            .values(status="stale")
        )
        await session.execute(
            update(RetrievalUnit)
            .where(RetrievalUnit.unit_id.in_(unit_ids))
            .values(status="isolated")
        )


async def _refresh_version_ingestion_state(session: AsyncSession, version_id: str) -> str:
    rows = (
        await session.execute(
            select(
                AssetVersionDocument.mandatory,
                AssetDocument.parse_disposition,
                DocumentParseRun.status,
            )
            .join(AssetDocument, AssetDocument.document_id == AssetVersionDocument.document_id)
            .outerjoin(
                DocumentParseRun,
                (DocumentParseRun.document_id == AssetDocument.document_id)
                & (DocumentParseRun.is_current.is_(True)),
            )
            .where(AssetVersionDocument.version_id == version_id)
        )
    ).all()
    mandatory = [row for row in rows if row.mandatory]
    if not mandatory:
        state = "needs_review"
    elif any(
        row.status in {ParseRunStatus.FAILED.value, ParseRunStatus.REQUIRES_OCR.value}
        for row in mandatory
    ):
        state = "blocked"
    elif any(row.status == ParseRunStatus.NEEDS_REVIEW.value for row in mandatory):
        state = "needs_review"
    elif any(
        row.parse_disposition == ParseDisposition.STRUCTURED.value
        and row.status != ParseRunStatus.SUCCEEDED.value
        for row in mandatory
    ):
        state = "processing"
    else:
        state = "ready"
    version = await session.get(AssetVersion, version_id)
    if version is not None:
        version.ingestion_state = state
    return state


async def parse_asset_document(session: AsyncSession, document_id: str) -> dict:
    document = await session.get(AssetDocument, document_id)
    if document is None:
        raise ValueError("资产文件不存在")
    data = get_object_store().get_object(document.object_key)
    if data is None:
        raise ValueError("资产原件不可读取")
    source_hash = hashlib.sha256(data).hexdigest()
    previous_current_ids = list((await session.execute(
        select(DocumentParseRun.parse_run_id).where(
            DocumentParseRun.document_id == document.document_id,
            DocumentParseRun.is_current.is_(True),
        )
    )).scalars())
    now = datetime.now(timezone.utc)
    run = DocumentParseRun(
        document_id=document.document_id,
        parser_name="pending",
        parser_version="1",
        status=ParseRunStatus.RUNNING.value,
        is_current=False,
        source_hash=source_hash,
        config_hash=hashlib.sha256(b"compound-asset-v2-parser-config-1").hexdigest(),
        started_at=now,
    )
    session.add(run)
    await session.flush()
    try:
        ast = parse_document_ast(document.filename, data)
        flat = flatten_ast(ast.root)
        citables = citable_nodes(flat)
        requires_ocr = Path(document.filename).suffix.lower() == ".pdf" and not citables
        parsed_chars = sum(len(_normalized(item.node.text).replace(" ", "")) for item in citables)
        coverage = min(parsed_chars / max(ast.source_chars, 1), 1.0) if ast.source_chars else 1.0
        anchored = sum(1 for item in citables if item.node.source_locator or item.node.source_page)
        anchor_ratio = anchored / max(len(citables), 1)
        warnings = list(ast.warnings)
        if ast.disposition == ParseDisposition.STRUCTURED.value and not citables:
            warnings.append("结构化文件未形成可引用节点")
        if ast.source_chars >= 1000 and coverage < 0.75:
            warnings.append(f"正文覆盖率不足（{coverage:.0%}）")
        if citables and anchor_ratio < 1.0:
            warnings.append(f"引用定位覆盖不足（{anchor_ratio:.0%}）")
        if requires_ocr:
            warnings.append("文件无可提取文字层；本系统不接收扫描原件，请先完成OCR后重新上传")
            status = ParseRunStatus.REQUIRES_OCR.value
            ast.disposition = ParseDisposition.EXCLUDED.value
        else:
            status = (
                ParseRunStatus.NEEDS_REVIEW.value
                if warnings and ast.disposition == ParseDisposition.STRUCTURED.value
                else ParseRunStatus.SUCCEEDED.value
            )

        await _isolate_retrieval_units_for_runs(session, previous_current_ids)
        await session.execute(
            update(DocumentParseRun)
            .where(
                DocumentParseRun.document_id == document.document_id,
                DocumentParseRun.is_current.is_(True),
            )
            .values(is_current=False)
        )
        path_to_id: dict[str, str] = {}
        for item in flat:
            node_id = gen_id("node")
            path_to_id[item.order_path] = node_id
            session.add(ContentNode(
                node_id=node_id,
                parse_run_id=run.parse_run_id,
                document_id=document.document_id,
                parent_id=path_to_id.get(item.parent_path or ""),
                node_type=item.node.node_type,
                order_path=item.order_path,
                ordinal=item.ordinal,
                label=item.node.label,
                title=item.node.title,
                text=item.node.text,
                normalized_text=_normalized(item.node.text),
                source_page=item.node.source_page,
                source_locator=item.node.source_locator,
                source_bbox=item.node.source_bbox,
                sheet_name=item.node.sheet_name,
                cell_range=item.node.cell_range,
                structure=item.node.structure,
                content_hash=item.node.content_hash,
                is_citable=item.node.citable,
            ))
        version_ids = list((await session.execute(
            select(AssetVersionDocument.version_id).where(
                AssetVersionDocument.document_id == document.document_id
            )
        )).scalars())
        for item in citables:
            node_id = path_to_id[item.order_path]
            quote = _normalized(item.node.text)
            segments = _retrieval_segments(quote)
            for segment_index, (start_offset, end_offset, unit_text) in enumerate(segments):
                span_id = gen_id("span")
                span = CitationSpan(
                    span_id=span_id,
                    node_id=node_id,
                    start_offset=start_offset,
                    end_offset=end_offset,
                    quote_text=unit_text,
                    content_hash=hashlib.sha256(unit_text.encode("utf-8")).hexdigest(),
                    locator={
                        "page": item.node.source_page,
                        "path": item.node.source_locator,
                        "bbox": item.node.source_bbox,
                        "sheet": item.node.sheet_name,
                        "cell_range": item.node.cell_range,
                        "segment": segment_index + 1,
                        "segment_count": len(segments),
                    },
                )
                session.add(span)
                for version_id in version_ids:
                    unit_id = gen_id("unit")
                    base_title = " ".join(part for part in (item.node.label, item.node.title) if part)
                    unit_title = (
                        f"{base_title}（片段{segment_index + 1}/{len(segments)}）"
                        if len(segments) > 1 else base_title
                    )
                    unit = RetrievalUnit(
                        unit_id=unit_id,
                        version_id=version_id,
                        unit_type=item.node.node_type,
                        title=unit_title,
                        text=unit_text,
                        content_hash=hashlib.sha256(unit_text.encode("utf-8")).hexdigest(),
                        secret_level=document.secret_level,
                        status="candidate" if status == ParseRunStatus.NEEDS_REVIEW.value else "verified",
                        unit_metadata={
                            "document_id": document.document_id,
                            "parse_run_id": run.parse_run_id,
                            "segment_index": segment_index,
                            "segment_count": len(segments),
                        },
                    )
                    session.add(unit)
                    session.add(RetrievalUnitSource(
                        unit_id=unit_id,
                        node_id=node_id,
                        span_id=span_id,
                        sequence=0,
                    ))

        document.parse_disposition = ast.disposition
        document.disposition_reason = (
            "无可提取文字层，需在系统外完成OCR后重新上传"
            if requires_ocr
            else None
        )
        run.parser_name = ast.parser_name
        run.parser_version = ast.parser_version
        run.status = status
        run.is_current = True
        run.finished_at = datetime.now(timezone.utc)
        run.coverage = coverage
        run.anchor_ratio = anchor_ratio
        run.parser_config = {"filename": document.filename, "disposition": ast.disposition}
        run.quality_report = {
            "node_count": len(flat),
            "citable_count": len(citables),
            "source_chars": ast.source_chars,
            "parsed_chars": parsed_chars,
            "coverage": round(coverage, 4),
            "anchor_ratio": round(anchor_ratio, 4),
            "warnings": warnings,
            "rejection_code": "requires_ocr" if requires_ocr else None,
        }
        run.error_summary = "requires_ocr" if requires_ocr else None
        states = {
            version_id: await _refresh_version_ingestion_state(session, version_id)
            for version_id in version_ids
        }
        await session.flush()
        return {
            "document_id": document.document_id,
            "parse_run_id": run.parse_run_id,
            "status": status,
            "parser": ast.parser_name,
            "disposition": ast.disposition,
            "node_count": len(flat),
            "citable_count": len(citables),
            "coverage": round(coverage, 4),
            "anchor_ratio": round(anchor_ratio, 4),
            "warnings": warnings,
            "version_states": states,
        }
    except Exception as exc:
        run.status = ParseRunStatus.FAILED.value
        # A failed reparse must not replace a previously usable snapshot.  For
        # a first parse, however, the failure is current state and must be
        # visible to operators instead of leaving the document as "pending".
        run.is_current = not previous_current_ids
        run.finished_at = datetime.now(timezone.utc)
        run.error_summary = str(exc)[:512]
        version_ids = list((await session.execute(
            select(AssetVersionDocument.version_id).where(
                AssetVersionDocument.document_id == document.document_id
            )
        )).scalars())
        for version_id in version_ids:
            await _refresh_version_ingestion_state(session, version_id)
        await session.flush()
        raise


async def discard_parse_run(session: AsyncSession, parse_run_id: str) -> None:
    """Delete an unpublished candidate snapshot and its derived units."""
    node_ids = list((await session.execute(
        select(ContentNode.node_id).where(ContentNode.parse_run_id == parse_run_id)
    )).scalars())
    unit_ids = list((await session.execute(
        select(RetrievalUnitSource.unit_id).where(RetrievalUnitSource.node_id.in_(node_ids))
    )).scalars()) if node_ids else []
    if unit_ids:
        await session.execute(delete(RetrievalUnitSource).where(RetrievalUnitSource.unit_id.in_(unit_ids)))
        await session.execute(delete(RetrievalUnit).where(RetrievalUnit.unit_id.in_(unit_ids)))
    if node_ids:
        span_ids = list((await session.execute(
            select(CitationSpan.span_id).where(CitationSpan.node_id.in_(node_ids))
        )).scalars())
        if span_ids:
            await session.execute(delete(CitationSpan).where(CitationSpan.span_id.in_(span_ids)))
        await session.execute(delete(ContentNode).where(ContentNode.node_id.in_(node_ids)))
    await session.execute(delete(DocumentParseRun).where(DocumentParseRun.parse_run_id == parse_run_id))
