"""Pluggable structured parser router with transparent local fallback."""
from __future__ import annotations

import logging
import re

import httpx

from app.core.config import get_settings
from app.services.ingestion.parser import RawClause, extract_text, parse_document, parse_text
from app.services.ingestion.quality import ParseQualityReport, assess_parse_quality

logger = logging.getLogger(__name__)


def _docling_markdown_to_clauses(markdown: str) -> list[RawClause]:
    lines: list[str] = []
    for raw in (markdown or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("<!-- image -->"):
            continue
        if line.startswith("#"):
            line = re.sub(r"^#+\s*", "", line)
        lines.append(line)
    return parse_text("\n".join(lines))


async def _parse_docling(filename: str, data: bytes) -> list[RawClause] | None:
    settings = get_settings()
    if not settings.DOCLING_BASE_URL.strip():
        return None
    url = settings.DOCLING_BASE_URL.rstrip("/") + "/v1/convert/file"
    form = {
        "to_formats": "md",
        "image_export_mode": "placeholder",
        "do_ocr": "false",
        "force_ocr": "false",
        "table_mode": "accurate",
        "do_table_structure": "true",
        "do_pdf_heading_hierarchy": "true",
        "abort_on_error": "true",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.DOCLING_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url, data=form,
                files={"files": (filename, data, "application/octet-stream")},
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("status") not in {"success", "partial_success"}:
            return None
        markdown = ((payload.get("document") or {}).get("md_content") or "").strip()
        return _docling_markdown_to_clauses(markdown) if markdown else None
    except Exception:  # noqa: BLE001 - auto mode must fall back locally
        logger.warning("docling_parse_fallback", extra={"filename": filename})
        if settings.DOCUMENT_PARSER_MODE.lower() == "docling":
            raise
        return None


async def parse_document_structured(
    filename: str, data: bytes,
) -> tuple[list[RawClause], ParseQualityReport]:
    """Parse with Docling when configured, otherwise use deterministic native adapters."""
    settings = get_settings()
    mode = settings.DOCUMENT_PARSER_MODE.lower()
    clauses: list[RawClause] | None = None
    backend = "native"
    if mode in {"auto", "docling"} and filename.lower().endswith((".pdf", ".docx", ".xlsx", ".xls")):
        clauses = await _parse_docling(filename, data)
        if clauses:
            backend = "docling"
    if not clauses:
        clauses = parse_document(filename, data)
    for index, clause in enumerate(clauses, start=1):
        if not clause.source_locator:
            clause.source_locator = f"unit:{index}"
    source_text = extract_text(filename, data)
    report = assess_parse_quality(
        source_text, clauses, backend=backend, filename=filename,
        minimum_score=settings.PARSE_QUALITY_MIN_SCORE,
    )
    return clauses, report
