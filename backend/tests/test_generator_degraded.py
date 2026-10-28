"""Generator graceful-degradation path (architecture §7.4).

If the LLM adapter fails (timeout), the generator must retry once and then
fall back to an explicit no-conclusion message flagged ``degraded=True``. Retrieval
candidates remain citations and must never be presented as an answer. The mock adapter always succeeds, so the
degraded branch (which the openai_compat adapter reaches via LLMTimeoutError)
is exercised here with a failing stub.
"""
from __future__ import annotations

from app.core.exceptions import LLMTimeoutError
from app.services.rag.generator import GeneratorService
from app.services.rag.retriever import RetrievedClause
from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile


class _FailingLLM:
    kind = "failing"

    async def chat(self, messages, **kwargs):  # noqa: ANN003
        raise LLMTimeoutError("simulated LLM timeout")


async def test_generator_falls_back_on_timeout():
    svc = GeneratorService()
    svc.llm = _FailingLLM()

    file = RegulationFile(title="境外项目管理办法", org_path="/", secret_level="internal", domain="*", status="current")
    clause = Clause(
        clause_id="c1", file_id="f1", clause_no="第12条",
        content="须报总部审批。", status="current",
    )
    candidates = [RetrievedClause(clause=clause, file=file, score=0.9)]

    answer, degraded = await svc.generate("境外项目变更款由谁审批？", candidates, {})

    assert degraded is True
    assert "系统已停止生成" in answer
    assert "须报总部审批" not in answer
