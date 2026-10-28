from __future__ import annotations

from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile
from app.services.rag.retriever import RetrievedClause, RetrieverService


class _Reranker:
    async def rerank(self, _query, _documents, top_n=None):
        return [(0, 0.31), (1, 0.22)]


async def test_reranker_keeps_absolute_low_scores_instead_of_forcing_top_to_one():
    file = RegulationFile(file_id="file_cal", title="制度", status="current")
    candidates = [
        RetrievedClause(
            Clause(clause_id=f"clause_cal_{idx}", file_id=file.file_id, clause_no=str(idx), content="条款"),
            file,
            score,
        )
        for idx, score in enumerate((0.4, 0.3), start=1)
    ]
    service = RetrieverService()
    service.reranker = _Reranker()
    result = await service._rerank_with_model("问题", candidates, 2)
    assert result[0].score < 0.5
    assert result[0].score != 1.0
