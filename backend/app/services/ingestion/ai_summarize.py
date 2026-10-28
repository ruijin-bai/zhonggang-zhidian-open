"""LLM document summarisation + metadata extraction for regulation files.

Produces a document-level summary (for two-stage retrieval and answer-context
aggregation) and pulls structured metadata — regulation_code / effective_date /
expiry_date / domain — that the current ingestion left blank. All functions
degrade to ``None`` on any model/parse failure.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime

from app.adapters.llm.factory import get_llm_adapter
from app.core.runtime_config import get_runtime_model_config

_SUMMARY_SYSTEM = (
    "你是企业制度的文档摘要专家。请为一整份制度文档撰写摘要，"
    "概括其适用范围、规范对象与核心管理要点，用于检索召回。"
)

_SUMMARY_PROMPT = """请为以下制度文档撰写一段摘要（150字以内，中文）：
- 一句话说明本制度管什么、适用于谁；
- 列出核心管理要点（3-5条，用分号分隔）；
- 突出关键实体（金额阈值、审批层级、期限、部门）。
只输出摘要正文，不要标题、不要 Markdown。

制度标题：{title}
制度正文（节选）：
{text}
"""

_META_SYSTEM = "你是企业制度文档的元数据抽取专家。"

_META_PROMPT = """请从以下制度文档中抽取元数据，严格输出 JSON（不要 Markdown 围栏）：
{{
  "regulation_code": "制度文号/编号（如 中港〔2024〕12号，无则空字符串）",
  "effective_date": "生效日期 YYYY-MM-DD（无则 null）",
  "expiry_date": "废止/失效日期 YYYY-MM-DD（无则 null）",
  "domain": "制度域（从 人事/财务/采购/工程/安全/合规/行政/综合 中选最贴切的一个，无法判断用 综合）"
}}

制度标题：{title}
制度正文（节选）：
{text}
"""


def _sanitize(raw: str) -> str:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        s = s[start : end + 1]
    return s.strip()


def _has_real_llm() -> bool:
    rt = get_runtime_model_config()
    return bool(rt and rt.enabled and rt.llm_api_key)


def _head(text: str, limit: int = 6000) -> str:
    return text if len(text) <= limit else text[:limit]


def _parse_date(s) -> date | None:
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, IndexError):
        return None


_CODE_HINT_RE = re.compile(r"[〔【\[][^〕】\]]*[〕】\]]|\d+\s*号")


def _valid_code(code: str, title: str) -> str:
    """Reject the common LLM mistake of echoing the title back as the code.

    A real regulation code carries a bracket/编号 marker (中港〔2024〕12号 /
    中港工程字[2022]号). If the value is just the title (or wraps it), treat as
    absent.
    """
    code = (code or "").strip()
    if not code:
        return ""
    if code == title or code in title or title in code:
        return ""
    if _CODE_HINT_RE.search(code):
        return code
    return ""


async def enrich_regulation(session, regulation, title: str, text: str) -> None:
    """Generate a document summary and extract metadata, writing back to ``regulation``.

    Degrades to a no-op when no real LLM is configured; each field is written
    independently so a partial failure never blocks ingestion.
    """
    if not _has_real_llm() or not text:
        return
    summary = await summarize_document(title, text)
    if summary:
        regulation.summary = summary
    meta = await extract_metadata(title, text)
    if meta:
        code = _valid_code(meta.get("regulation_code"), title)
        if code and not regulation.regulation_code:
            regulation.regulation_code = code
        ed = _parse_date(meta.get("effective_date"))
        if ed and not regulation.effective_date:
            regulation.effective_date = ed
        xd = _parse_date(meta.get("expiry_date"))
        if xd and not regulation.expiry_date:
            regulation.expiry_date = xd
        if meta.get("domain") and regulation.domain in ("*", ""):
            regulation.domain = meta["domain"]
    await session.flush()


async def summarize_document(title: str, text: str, timeout: float = 30.0) -> str | None:
    """Return a concise document summary, or None on failure."""
    try:
        result = await get_llm_adapter().chat(
            [
                {"role": "system", "content": _SUMMARY_SYSTEM},
                {"role": "user", "content": _SUMMARY_PROMPT.format(title=title, text=_head(text))},
            ],
            timeout=timeout,
            max_tokens=512,
            temperature=0.2,
        )
        summary = (result.content or "").strip()
        return summary or None
    except Exception:  # noqa: BLE001
        return None


async def extract_metadata(title: str, text: str, timeout: float = 30.0) -> dict | None:
    """Return {regulation_code, effective_date, expiry_date, domain} or None."""
    try:
        result = await get_llm_adapter().chat(
            [
                {"role": "system", "content": _META_SYSTEM},
                {"role": "user", "content": _META_PROMPT.format(title=title, text=_head(text))},
            ],
            timeout=timeout,
            max_tokens=256,
            temperature=0.0,
        )
        obj = json.loads(_sanitize(result.content))
        if not isinstance(obj, dict):
            return None
        return {
            "regulation_code": str(obj.get("regulation_code") or "").strip(),
            "effective_date": obj.get("effective_date"),
            "expiry_date": obj.get("expiry_date"),
            "domain": str(obj.get("domain") or "综合").strip() or "综合",
        }
    except Exception:  # noqa: BLE001
        return None
