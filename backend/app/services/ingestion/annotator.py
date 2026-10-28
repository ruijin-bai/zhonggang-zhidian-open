"""Structured annotation: auto-tagging + permission-level detection + persistence."""
from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import gen_id
from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile
from app.db.models.tag import Tag, clause_tag
from app.services.ingestion.parser import RawClause

# Keyword → scenario-tag dictionary for heuristic annotation.
_SCENARIO_KEYWORDS: dict[str, str] = {
    "报销": "报销",
    "差旅": "差旅",
    "采购": "采购",
    "招标": "采购",
    "出境": "出境",
    "出国": "出境",
    "驻外": "驻外",
    "境外": "境外项目",
    "变更款": "变更款审批",
    "变更": "变更管理",
    "审批": "审批权限",
    "核准": "审批权限",
    "权限": "审批权限",
    "预算": "预算管理",
    "合同": "合同管理",
}

_PERMISSION_HINTS = ["审批", "核准", "权限", "由", "须报", "报", "批准"]


def auto_tag(content: str) -> list[str]:
    tags: list[str] = []
    for kw, tag in _SCENARIO_KEYWORDS.items():
        if kw in (content or ""):
            tags.append(tag)
    # de-dup keep order
    return list(dict.fromkeys(tags))


def detect_permission_level(content: str) -> str | None:
    if any(h in (content or "") for h in _PERMISSION_HINTS):
        return "needs_approval"
    return None


async def _ensure_tag(session: AsyncSession, tag_type: str, tag_value: str) -> Tag:
    result = await session.execute(
        select(Tag).where(Tag.tag_type == tag_type, Tag.tag_value == tag_value)
    )
    tag = result.scalar_one_or_none()
    if tag is None:
        tag = Tag(tag_id=gen_id("tag"), tag_type=tag_type, tag_value=tag_value)
        session.add(tag)
        await session.flush()
    return tag


async def create_regulation_with_clauses(
    session: AsyncSession,
    *,
    title: str,
    source: str,
    version: str,
    owner_org: str | None,
    org_path: str,
    secret_level: str,
    domain: str,
    lang: str,
    object_key: str | None,
    clauses: list[RawClause],
) -> RegulationFile:
    """Persist a regulation file and its (not-yet-embedded) clauses."""
    file = RegulationFile(
        title=title,
        source=source,
        version=version,
        owner_org=owner_org,
        org_path=org_path,
        secret_level=secret_level,
        domain=domain,
        lang=lang,
        object_key=object_key,
        status="current",
    )
    session.add(file)
    await session.flush()

    for rc in clauses:
        tags = auto_tag(rc.content)
        clause = Clause(
            file_id=file.file_id,
            chapter=rc.chapter,
            clause_no=rc.clause_no,
            content=rc.content,
            source_page=rc.source_page,
            source_locator=rc.source_locator,
            heading_path=rc.heading_path,
            block_type=rc.block_type,
            content_hash=hashlib.sha256(rc.content.encode("utf-8")).hexdigest(),
            permission_level=detect_permission_level(rc.content),
            secret_level=secret_level,
            scenario_tags=tags,
            embedding=None,
            status="current",
        )
        session.add(clause)
        await session.flush()
        for tv in tags:
            tag = await _ensure_tag(session, "业务场景", tv)
            await session.execute(clause_tag.insert().values(clause_id=clause.clause_id, tag_id=tag.tag_id))
    return file


async def append_clauses_to_file(
    session: AsyncSession,
    file_id: str,
    clauses: list[RawClause],
    secret_level: str = "internal",
) -> int:
    """Append parsed clauses to an *already persisted* regulation file.

    Used by the asynchronous ingestion pipeline: the upload endpoint first
    creates a ``processing`` record, then a background task calls this to fill
    in the clauses once LLM/rule-based splitting finishes.
    """
    n = 0
    for rc in clauses:
        tags = auto_tag(rc.content)
        clause = Clause(
            file_id=file_id,
            chapter=rc.chapter,
            clause_no=rc.clause_no,
            content=rc.content,
            source_page=rc.source_page,
            source_locator=rc.source_locator,
            heading_path=rc.heading_path,
            block_type=rc.block_type,
            content_hash=hashlib.sha256(rc.content.encode("utf-8")).hexdigest(),
            permission_level=detect_permission_level(rc.content),
            secret_level=secret_level,
            scenario_tags=tags,
            embedding=None,
            status="current",
        )
        session.add(clause)
        await session.flush()
        for tv in tags:
            tag = await _ensure_tag(session, "业务场景", tv)
            await session.execute(clause_tag.insert().values(clause_id=clause.clause_id, tag_id=tag.tag_id))
        n += 1
    return n
