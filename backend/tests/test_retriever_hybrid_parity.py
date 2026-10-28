"""The common ranker used by SQLite and PostgreSQL keeps lexical evidence."""
from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile
from app.services.rag.retriever import RetrieverService


def test_hybrid_ranker_promotes_exact_policy_code_when_vectors_tie():
    exact_file = RegulationFile(file_id="f_exact", title="CHEC-PM-2026-001 项目办法")
    other_file = RegulationFile(file_id="f_other", title="项目管理通则")
    exact = Clause(
        clause_id="c_exact", file_id="f_exact", clause_no="第1条",
        content="CHEC-PM-2026-001 的适用范围。", embedding=[1.0, 0.0], secret_level="internal",
    )
    other = Clause(
        clause_id="c_other", file_id="f_other", clause_no="第1条",
        content="项目管理的一般要求。", embedding=[1.0, 0.0], secret_level="internal",
    )
    ranked = RetrieverService()._rank_candidates(
        [(other, other_file), (exact, exact_file)], [1.0, 0.0],
        "CHEC-PM-2026-001 适用范围", top_k=2, min_score=0,
    )
    assert ranked[0].clause.clause_id == "c_exact"
