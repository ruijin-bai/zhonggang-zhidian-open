"""Citation boundary & answer-degradation tests (T08 / §4.2).

Focuses on the *edges* not covered by test_citation.py:
  * CitationService.build_citations on empty input (graceful empty card list).
  * check_consistency boundary (empty / mismatched → False).
  * Long clause content truncation → still consistent (省略号剥离后仍是原文子串).
  * verify() marks a citation inconsistent when the source map is missing.
  * QAService.ask with empty retrieval → degraded=True + human hand-off (low-confidence fallback).
"""
from __future__ import annotations

from app.db.models.clause import Clause
from app.db.models.permission import Permission
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.services.qa_service import QAService
from app.services.rag.citation import CitationService
from app.services.rag.retriever import RetrievedClause


def test_build_citations_empty_returns_empty():
    assert CitationService().build_citations([]) == []


def test_check_consistency_boundary():
    svc = CitationService()
    # Empty inputs must never be reported as "consistent".
    assert svc.check_consistency("", "原文") is False
    assert svc.check_consistency("片段", "") is False
    assert svc.check_consistency("", "") is False
    # Mismatched excerpt is inconsistent.
    assert svc.check_consistency("不存在的片段", "原文内容") is False


def test_build_citations_long_content_truncated_but_consistent():
    file = RegulationFile(title="长条款办法", org_path="/", secret_level="internal", domain="*", status="current")
    long_text = "境外项目" * 200  # far exceeds the 400-char truncation limit
    clause = Clause(clause_id="c_long", file_id="f_long", clause_no="第1条", content=long_text, status="current")
    candidates = [RetrievedClause(clause=clause, file=file, score=0.9)]
    cites = CitationService().build_citations(candidates, limit=400)
    assert len(cites) == 1
    cit = cites[0]
    # 截断摘录（前 N 字 + 省略号）依然源自原文，应判定为一致；
    # 若误判为不一致，评估的「引用率」会对所有长条款恒为 0。
    assert cit.consistent is True
    assert len(cit.excerpt) <= 400
    assert cit.excerpt.endswith("…")


def test_verify_marks_inconsistent_when_source_missing():
    file = RegulationFile(title="办法", org_path="/", secret_level="internal", domain="*", status="current")
    clause = Clause(clause_id="c1", file_id="f1", clause_no="第1条", content="原始条款全文内容", status="current")
    candidates = [RetrievedClause(clause=clause, file=file, score=0.9)]
    cites = CitationService().build_citations(candidates)
    assert cites[0].consistent is True

    # Re-verify against a clause map that is missing the source → must mark inconsistent.
    ok, rechecked = CitationService().verify(cites, clause_map={})
    assert ok is False
    assert rechecked[0].consistent is False


async def test_qa_ask_empty_retrieval_is_degraded(session):
    user = User(user_id="u_qa", username="u_qa", role="R4", secret_clearance="secret")
    perms = [Permission(role="R4", org_scope="/", secret_level="secret", domain="*")]
    svc = QAService()
    result = await svc.ask(
        session, user=user, permissions=perms, question="一个库里没有任何相关条款的冷门问题？"
    )
    assert result["degraded"] is True
    assert result["citations"] == []
    assert result["confidence"] == 0.0
    assert result["need_human"] is True
