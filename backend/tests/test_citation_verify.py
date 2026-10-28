"""CitationService.verify() — re-check excerpts against a source map (T08).

``build_citations`` + ``check_consistency`` are covered in ``test_citation.py``.
Here we exercise ``verify`` directly: a tampered excerpt must be flagged
inconsistent so the answer's 引用校验 (architecture §3.2 ①) can fail loudly.
"""
from __future__ import annotations

from app.services.rag.citation import CitationService
from app.services.rag.retriever import RetrievedClause
from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile


def test_verify_flags_tampered_excerpt():
    file = RegulationFile(title="办法", org_path="/", secret_level="internal", domain="*", status="current")
    clause = Clause(
        clause_id="c1", file_id="f1", clause_no="第1条",
        content="原始条款全文内容", status="current",
    )
    candidates = [RetrievedClause(clause=clause, file=file, score=0.9)]
    cites = CitationService().build_citations(candidates)

    # Simulate an answer that quoted something NOT in the source clause.
    cites[0].excerpt = "凭空捏造的摘录"
    ok, verified = CitationService().verify(cites, {clause.clause_id: clause.content})

    assert ok is False
    assert verified[0].consistent is False


def test_verify_passes_for_verbatim_excerpt():
    file = RegulationFile(title="办法", org_path="/", secret_level="internal", domain="*", status="current")
    clause = Clause(
        clause_id="c1", file_id="f1", clause_no="第1条",
        content="原始条款全文内容", status="current",
    )
    candidates = [RetrievedClause(clause=clause, file=file, score=0.9)]
    cites = CitationService().build_citations(candidates)
    ok, verified = CitationService().verify(cites, {clause.clause_id: clause.content})

    assert ok is True
    assert verified[0].consistent is True
