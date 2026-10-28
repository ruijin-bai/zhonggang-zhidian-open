"""Mock LLM adapter — runs with NO API key and drives the full QA chain.

The mock does not fabricate: it parses the ``<<CLAUSE>>`` context blocks that the
generator injects into the prompt and assembles a partitioned answer that quotes
the retrieved clause text verbatim. System prompt ("仅依据检索片段、不编造")
is honoured because every emitted sentence references a real clause.
"""
from __future__ import annotations

import re

from app.adapters.llm.base import ChatResult, LLMAdapter
from app.core.config import get_settings
from collections.abc import AsyncIterator

_SETTINGS = get_settings()

_CLAUSE_RE = re.compile(
    r'<<CLAUSE\s+file="(?P<file>.*?)"\s+no="(?P<no>.*?)".*?>>(?P<body>.*?)<</CLAUSE>>',
    re.DOTALL,
)


def _extract_sentences(text: str, keywords: list[str]) -> list[str]:
    """Return sentences from *text* that contain any of *keywords* (quoted, no fabrication)."""
    sentences = re.split(r"[。；;！!?\n]", text)
    out: list[str] = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if any(k in s for k in keywords):
            out.append(s)
    return out[:3]


def assemble_answer(user_content: str, question: str = "") -> str:
    """Assemble an AI 解读 answer from the injected clause context."""
    blocks = _CLAUSE_RE.findall(user_content)
    if not blocks:
        return (
            "抱歉，本次检索未命中可引用的制度条款，无法给出确定性结论。"
            "建议补充业务场景关键信息（如金额、境内外、审批层级）后重新提问，或联系职能审核骨干确认。"
        )

    titles: list[str] = []
    nos: list[str] = []
    corpus = ""
    for file_title, no, body in blocks:
        if file_title not in titles:
            titles.append(file_title)
        nos.append(f"《{file_title}》{no}")
        corpus += body + "。"
    refs = "".join(f"[{index}]" for index in range(1, len(blocks) + 1))

    approval = _extract_sentences(corpus, ["审批", "核准", "审核", "须", "应报", "报"])
    material = _extract_sentences(corpus, ["材料", "提交", "附", "证件", "证明"])
    notice = _extract_sentences(corpus, ["注意", "不得", "禁止", "须", "应", "风险"])

    lines = ["根据检索到的制度条款，为您解读如下：" + refs, ""]
    lines.append("【适用制度】" + "；".join(titles) + refs)
    lines.append("【核心条款】" + "；".join(nos) + refs)
    lines.append(
        "【审批权限】"
        + ("；".join(approval) if approval else "检索结果未明确列出审批权限，请以条款原文为准或补充审批层级后追问。")
        + refs
    )
    lines.append(
        "【所需材料】"
        + ("；".join(material) if material else "检索结果未单独列示材料清单，请查阅上方条款原文或补充场景后追问。")
        + refs
    )
    lines.append(
        "【注意事项】"
        + ("；".join(notice) if notice else "检索条款未列出更多注意事项，请提交人工复核。")
        + refs
    )
    return "\n".join(lines)


class MockLLMAdapter(LLMAdapter):
    kind = "mock"

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1500,
        timeout: float = 45.0,
    ) -> ChatResult:
        # The user turn carries the clause context; we assemble from it.
        user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_content = msg.get("content", "")
                break
        # Query rewriting is part of the default QA pipeline. The mock has no
        # semantic rewrite capability, so preserving the original question is
        # the deterministic, non-fabricating fallback that keeps local/CI
        # retrieval usable without an external model.
        if "查询改写助手" in user_content:
            question = user_content.rsplit("：\n", 1)[-1].strip()
            return ChatResult(content=question, finish_reason="stop", model="mock-llm", usage={})
        content = assemble_answer(user_content)
        return ChatResult(content=content, finish_reason="stop", model="mock-llm", usage={})

    async def stream(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1500,
        timeout: float = 45.0,
    ) -> AsyncIterator[str]:
        """Mock streaming: assemble from clause context and yield sentence-by-sentence."""
        user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_content = msg.get("content", "")
                break
        content = assemble_answer(user_content)
        for part in re.split(r"(\n)", content):
            if part:
                yield part
