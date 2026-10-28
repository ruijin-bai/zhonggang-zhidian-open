"""Query rewriting: rewrite colloquial questions into cleaner retrieval queries.

Used by the QA pipeline to improve recall on ellipsis / spoken-language questions
(architecture §6 T07+, "让 AI 做更多" enhancement).
"""
from __future__ import annotations

from app.adapters.llm.factory import get_llm_adapter
from app.core.config import get_settings

_SETTINGS = get_settings()


def _needs_rewrite(question: str) -> bool:
    """规则预判：仅明显口语化/省略的问句才需要 LLM 改写。

    交融 MaaS 单次调用固定 2~4s，对「员工借调需要什么流程」这类本就规范的
    问句改写是纯浪费（改写后常与原文相同）。用轻量规则短路，规范问句直接
    用原文检索，把省下的时延留给生成。
    """
    q = (question or "").strip()
    if len(q) < 8:
        return True  # 过短，大概率是省略/代词回指，需要改写补全
    for w in ("咋", "啥", "怎么弄", "多少钱", "咋办", "咋整", "怎么办呀", "这个", "那个"):
        if w in q:
            return True
    return False


async def rewrite_query(question: str) -> str:
    """Rewrite a colloquial/elliptical question into a retrieval-friendly query.

    Falls back to the original question on any failure (timeout / disabled / parse)
    so retrieval is never blocked. 规范问句由 ``_needs_rewrite`` 短路，省一次调用。
    """
    if not _SETTINGS.QA_REWRITE_ENABLED or not _needs_rewrite(question):
        return question
    try:
        prompt = (
            "你是企业制度检索的查询改写助手。请将用户的口语化、含省略的问题改写为"
            "适合向量检索的规范查询句，保留关键实体（金额、境内外、事项、审批层级等），"
            "只返回改写后的查询句本身，不要解释、不要标点以外的修饰：\n" + question
        )
        result = await get_llm_adapter(fast=True).chat(
            [{"role": "user", "content": prompt}],
            timeout=_SETTINGS.QA_REWRITE_TIMEOUT,
            # The fast reasoning model may use >100 internal reasoning tokens
            # before the short rewritten query appears in ``content``.
            max_tokens=256,
            temperature=0.0,
        )
        txt = (result.content or "").strip().strip('"').strip("'").strip()
        return txt or question
    except Exception:  # noqa: BLE001
        return question
