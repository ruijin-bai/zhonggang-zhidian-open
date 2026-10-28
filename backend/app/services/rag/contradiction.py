"""Contradiction detection among retrieved clauses (confidence refinement).

Feeds the QA confidence score: a detected contradiction lowers confidence and
flags the answer for human review (architecture §6 T08+, confidence refinement).
"""
from __future__ import annotations

import json

from app.adapters.llm.factory import get_llm_adapter
from app.core.config import get_settings
from app.services.rag.retriever import RetrievedClause

_SETTINGS = get_settings()


async def detect_contradiction(
    question: str, candidates: list[RetrievedClause]
) -> tuple[bool, str]:
    """Detect whether the retrieved clauses contradict each other w.r.t. the question.

    Returns (has_contradiction, detail). Falls back to (False, "") on any failure
    (timeout / disabled / parse error) so the pipeline never blocks.
    """
    if not _SETTINGS.QA_CONTRADICTION_ENABLED or len(candidates) < 2:
        return False, ""
    try:
        items = "\n".join(
            f"《{c.file.title}》{c.clause.clause_no}：{c.clause.content}" for c in candidates
        )
        prompt = (
            "针对用户问题，判断下列制度条款之间是否存在相互矛盾的规定（即针对不同情形"
            "给出相反结论，而非单纯适用范围不同）。\n"
            f"用户问题：{question}\n条款：\n{items}\n"
            "只返回 JSON：{\"contradiction\": true 或 false, \"detail\": \"矛盾点简述，无则空串\"}"
        )
        result = await get_llm_adapter(fast=True).chat(
            [{"role": "user", "content": prompt}],
            timeout=_SETTINGS.QA_CONTRADICTION_TIMEOUT,
            max_tokens=256,
            temperature=0.0,
        )
        obj = json.loads(result.content)
        return bool(obj.get("contradiction")), str(obj.get("detail", "") or "")
    except Exception:  # noqa: BLE001
        return False, ""
