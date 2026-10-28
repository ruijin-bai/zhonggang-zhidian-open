"""Citation consistency tests (T08)."""
from __future__ import annotations

from app.services.rag.citation import CitationService
from app.services.rag.retriever import RetrievedClause
from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile


def test_check_consistency_verbatim():
    svc = CitationService()
    assert svc.check_consistency("须报总部审批", "单笔超过50万美元须报总部审批。") is True
    assert svc.check_consistency("不存在的片段", "原文内容") is False


def test_build_citations_uses_verbatim_excerpt():
    file = RegulationFile(title="办法", org_path="/", secret_level="internal", domain="*", status="current")
    clause = Clause(clause_id="c1", file_id="f1", clause_no="第1条", content="原始条款全文内容", status="current")
    candidates = [RetrievedClause(clause=clause, file=file, score=0.9)]
    cites = CitationService().build_citations(candidates)
    assert cites[0].excerpt == "原始条款全文内容"
    assert cites[0].consistent is True
