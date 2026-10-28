"""Agentic self-check: assess retrieval sufficiency and drive refine/retry loops.

The core upgrade over a "fire-once" retriever. After retrieval the LLM judges
whether the returned clauses actually answer the question. If not, it produces a
refined retrieval query (re-querying with the *missing aspect* made explicit) so
the pipeline self-corrects instead of answering confidently from the wrong
clauses. Degrades gracefully to ``None`` on any model/parse failure.
"""
from __future__ import annotations

import json

from app.adapters.llm.factory import get_llm_adapter
from app.core.config import get_settings
from app.services.rag.retriever import RetrievedClause

_SETTINGS = get_settings()

_SYSTEM = "你是企业制度检索的质量评估专家。你的职责是判断检索到的条款是否足以回答用户问题。"

_PROMPT = """请评估下列检索结果能否充分回答用户问题。

用户问题：{question}

检索到的制度条款：
{context}

请严格输出 JSON（不要 Markdown 围栏、不要解释）：
{{
  "sufficient": true 或 false,
  "score": 0-10 的整数（10=完全充分），
  "missing_aspect": "若不足，缺失的关键信息点是什么（一句中文，充分则为空字符串）",
  "refined_query": "若不足，改写后的检索句（补充缺失的关键词/实体，充分则返回原问题）"
}}
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


async def assess_retrieval(
    question: str,
    candidates: list[RetrievedClause],
    timeout: float | None = None,
) -> dict | None:
    """Judge whether ``candidates`` suffice for ``question``.

    Returns ``{"sufficient": bool, "score": int, "missing_aspect": str,
    "refined_query": str}`` or ``None`` on any failure (timeout / parse / no
    candidates) so callers can fall back to the non-self-checking path.
    """
    if not candidates:
        return None
    timeout = timeout or _SETTINGS.QA_SELFCHECK_TIMEOUT
    context = "\n".join(
        f"[{i}] 《{c.file.title}》{c.clause.clause_no}：{c.clause.content[:200]}"
        for i, c in enumerate(candidates[:8])
    )
    try:
        result = await get_llm_adapter(fast=True).chat(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _PROMPT.format(question=question, context=context)},
            ],
            timeout=timeout,
            max_tokens=320,
            temperature=0.0,
        )
        obj = json.loads(_sanitize(result.content))
        sufficient = bool(obj.get("sufficient", True))
        score = int(obj.get("score", 5))
        missing_aspect = str(obj.get("missing_aspect") or "").strip()
        refined_query = str(obj.get("refined_query") or "").strip() or question
        return {
            "sufficient": sufficient,
            "score": score,
            "missing_aspect": missing_aspect,
            "refined_query": refined_query,
        }
    except Exception:  # noqa: BLE001
        return None
