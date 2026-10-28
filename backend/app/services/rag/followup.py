"""Smart follow-up: slot detection + questioning strategy (architecture §6 T09).

Triggers when an approval/permission question is missing critical slots
(amount / 境内外 / 审批层级 / 涉及部门). Converges within FOLLOWUP_MAX_ROUNDS.
"""
from __future__ import annotations

import re

from app.adapters.llm.factory import get_llm_adapter
from app.core.config import get_settings
from app.services.rag.retriever import RetrievedClause
from app.utils.text import contains_any

_SETTINGS = get_settings()

SLOT_DEFS: dict[str, dict] = {
    "amount": {
        "label": "金额及币种",
        "options": ["填写准确金额与币种"],
    },
    "domestic": {
        "label": "境内外属性",
        "options": ["境内", "境外"],
    },
    "level": {
        "label": "审批层级",
        "options": ["项目部", "区域", "总部"],
    },
    "department": {
        "label": "涉及部门",
        "options": ["财务", "合规", "采购", "人事", "法务"],
    },
    "target_grade": {
        "label": "目标职级口径",
        "options": ["M5-1", "M5-2"],
    },
    "current_experience": {
        "label": "到达M2时累计工作年限",
        "options": ["不足3年", "已满3年", "不确定"],
    },
}

_APPROVAL_HINTS = ["审批", "权限", "由谁", "核准", "批准", "谁批", "怎么报", "如何审批", "报批", "谁来批"]
_AMOUNT_RE = re.compile(r"(\d+)\s*(万|元|美元|usd|us$|￥|\$)", re.IGNORECASE)
_GRADE_DURATION_RE = re.compile(
    r"(?i)M\s*\d+(?:-\d+)?\s*(?:到|至|→|->)\s*M\s*\d+(?:-\d+)?"
)


class FollowUpService:
    """Detect filled slots and build follow-up prompts."""

    def detect_slots(self, text: str, provided: dict | None = None) -> dict:
        filled: dict = dict(provided or {})

        if "amount" not in filled:
            m = _AMOUNT_RE.search(text or "")
            if m:
                # QA only records that an amount was supplied.  Its text
                # retrieval flow must never infer approval boundaries; exact
                # comparison belongs to the governed rule evaluator.
                filled["amount"] = f"{m.group(1)}{m.group(2)}"

        if "domestic" not in filled:
            if contains_any(text, ["境外", "海外", "驻外", "国外"]):
                filled["domestic"] = "境外"
            elif contains_any(text, ["境内", "国内"]):
                filled["domestic"] = "境内"

        if "level" not in filled:
            if contains_any(text, ["总部", "集团", "公司"]):
                filled["level"] = "总部"
            elif contains_any(text, ["区域"]):
                filled["level"] = "区域"
            elif contains_any(text, ["项目部", "项目级"]):
                filled["level"] = "项目部"

        if "department" not in filled:
            for d in ["财务", "合规", "采购", "人事", "法务"]:
                if d in (text or ""):
                    filled["department"] = d
                    break
        if "target_grade" not in filled:
            target = re.search(r"(?i)(?:到|至|→|->)\s*(M\s*\d+-\d+)", text or "")
            if target:
                filled["target_grade"] = re.sub(r"\s+", "", target.group(1)).upper()
        if "current_experience" not in filled:
            experience = re.search(r"(?:累计|已有|工作)\s*(\d+)\s*年", text or "")
            if experience:
                filled["current_experience"] = f"{experience.group(1)}年"
        return filled

    def _is_approval_question(self, text: str) -> bool:
        return contains_any(text, _APPROVAL_HINTS)

    def missing_slots(self, text: str, filled: dict, round_no: int) -> list[str]:
        if _GRADE_DURATION_RE.search(text or "") and contains_any(
            text, ["多久", "几年", "年限", "最短时间", "最长时间"]
        ):
            return [
                slot for slot in ("target_grade", "current_experience")
                if slot not in filled
            ]
        if not self._is_approval_question(text):
            return []
        required = ["amount", "domestic"]
        return [s for s in required if s not in filled]

    def build_followup(self, missing: list[str], round_no: int) -> dict:
        prompts = [
            {
                "slot": s,
                "label": SLOT_DEFS.get(s, {}).get("label", s),
                "options": SLOT_DEFS.get(s, {}).get("options", ["请补充具体信息"]),
            }
            for s in missing
        ]
        return {"round": round_no, "missing": missing, "prompts": prompts}

    async def dynamic_followup(
        self, question: str, candidates: list[RetrievedClause], round_no: int
    ) -> dict | None:
        """LLM-generated clarification questions derived from weak retrieval results.

        Instead of fixed slots, the model infers *what* the user must supply to get a
        deterministic answer, given the retrieved (but insufficient) clauses. Returns a
        followup payload (round/missing/prompts) or None on any failure (timeout / parse).
        """
        try:
            ctx = "\n".join(
                f"《{c.file.title}》{c.clause.clause_no}：{c.clause.content[:160]}"
                for c in candidates[:3]
            )
            prompt = (
                "用户问题：{q}\n当前检索到的制度片段有限或不够确定，不足以给出明确答案。\n"
                "请列出用户还需补充哪些关键信息点（最多3个）才能准确回答，"
                "每个点给一个简短中文标签(label)和2-4个候选选项(options)。\n"
                "只返回 JSON：{{\"prompts\":[{{\"label\":\"标签\",\"options\":[\"选项1\",\"选项2\"]}}]}}\n"
                "检索片段：\n{ctx}"
            ).format(q=question, ctx=ctx)
            r = await get_llm_adapter(fast=True).chat(
                [{"role": "user", "content": prompt}],
                timeout=10.0,
                max_tokens=320,
                temperature=0.0,
            )
            import json
            raw = (r.content or "").strip()
            # LLM 常把 JSON 包在 ```json ... ``` 围栏里，先剥离再解析
            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.lower().startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end > start:
                raw = raw[start:end + 1]
            obj = json.loads(raw)
            prompts_raw = obj.get("prompts") or []
            # 规范化：FollowUpPrompt schema 要求 slot/label/options 均存在
            prompts = []
            for i, p in enumerate(prompts_raw[:3]):
                label = str(p.get("label") or f"补充信息{i + 1}").strip()
                options = [str(o) for o in (p.get("options") or []) if str(o).strip()][:4]
                prompts.append({"slot": f"dyn_{i}", "label": label, "options": options or ["请补充具体信息"]})
            if not prompts:
                return None
            missing = [p["label"] for p in prompts]
            return {"round": round_no, "missing": missing, "prompts": prompts, "dynamic": True}
        except Exception:  # noqa: BLE001
            return None
