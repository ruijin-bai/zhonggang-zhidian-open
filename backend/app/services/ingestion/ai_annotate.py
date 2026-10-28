"""LLM-based automatic tagging (annotation) of clauses.

After a regulation is ingested, this runs (typically as a background task
triggered from the upload endpoint) and asks the LLM to label every clause
with business ``scenario_tags``, a ``secret_level`` and a ``permission_level``.
Results are written back to the clause rows so they surface in the admin
annotation UI and can be manually corrected later.

Designed to degrade gracefully: with no real LLM configured, or on any API /
parse failure, it returns 0 and leaves clauses untouched.
"""
from __future__ import annotations

import json
import re
from sqlalchemy import select

from app.adapters.llm.factory import get_llm_adapter
from app.core.runtime_config import get_runtime_model_config
from app.db.models.clause import Clause

_SECRET_LEVELS = ["public", "internal", "confidential", "secret"]

_SYSTEM = "你是企业制度的智能标注助手，负责为制度条款标注业务场景、密级与权限级别。"

_PROMPT = """下面是一份制度的若干条款，请为每条标注：
- scenario_tags: 该条款适用的业务场景标签数组（如["差旅","报销"]、["招标","采购"]、["安全生产"]，用简洁中文，最多5个）；
- secret_level: 密级，只能从 ["public","internal","confidential","secret"] 中选一个（公开/内部/机密/绝密）；
- permission_level: 阅读或执行该条款所需的权限级别（如"全体员工""部门负责人""领导班子""财务岗"等中文短语）。

请严格输出 JSON 数组，每项含字段 clause_no(与输入完全一致)、scenario_tags、secret_level、permission_level。
仅输出 JSON，不要解释或 Markdown 代码块标记。

条款列表：
{items}
"""


def _has_real_llm_cfg() -> bool:
    rt = get_runtime_model_config()
    return bool(rt and rt.enabled and rt.llm_api_key)


def _sanitize(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    return s.strip()


async def ai_annotate_clauses(file_id: str) -> int:
    """Annotate all current clauses of ``file_id`` via LLM. Returns clause count."""
    if not _has_real_llm_cfg():
        return 0
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        result = await session.execute(
            select(Clause).where(Clause.file_id == file_id, Clause.status == "current")
        )
        clauses = list(result.scalars().all())
        if not clauses:
            return 0

        items = [
            {"clause_no": c.clause_no, "content": (c.content or "")[:400].replace("\n", " ")}
            for c in clauses
        ]
        adapter = get_llm_adapter()
        ann_map: dict[str, dict] = {}
        try:
            resp = await adapter.chat(
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": _PROMPT.format(items=json.dumps(items, ensure_ascii=False))},
                ],
                temperature=0.2,
                max_tokens=6000,
                timeout=90.0,
            )
            parsed = json.loads(_sanitize(resp.content))
            if isinstance(parsed, list):
                for row in parsed:
                    if isinstance(row, dict) and row.get("clause_no"):
                        ann_map[row["clause_no"]] = row
        except Exception:
            return 0

        for c in clauses:
            ann = ann_map.get(c.clause_no)
            if not ann:
                continue
            tags = ann.get("scenario_tags")
            if isinstance(tags, list) and tags:
                c.scenario_tags = [str(t) for t in tags][:5]
            sl = ann.get("secret_level")
            if sl in _SECRET_LEVELS:
                c.secret_level = sl
            pl = ann.get("permission_level")
            if pl and isinstance(pl, str):
                c.permission_level = pl[:32]
        await session.commit()
    return len(clauses)
