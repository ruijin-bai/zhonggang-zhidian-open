from __future__ import annotations

from datetime import date

from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile
from app.services.governance_state import authority_gaps, is_authority_verified
from app.services.rag.grounding import evaluate_grounding
from app.services.rag.retriever import RetrievedClause


def _candidate(content: str = "单笔金额超过50万美元的，应报总部审批。") -> RetrievedClause:
    file = RegulationFile(
        file_id="file_grounding", regulation_code="中港〔2026〕1号", title="审批办法",
        status="current", effective_date=date(2026, 1, 1), owner_org="org_owner", domain="工程",
    )
    clause = Clause(
        clause_id="clause_grounding", file_id=file.file_id, clause_no="第十条",
        content=content, status="current", secret_level="internal",
    )
    return RetrievedClause(clause=clause, file=file, score=0.8)


def test_grounding_requires_claim_level_citation_and_checks_numbers():
    candidates = [_candidate()]
    passed = evaluate_grounding("金额超过50万美元时，应报总部审批。[1]", candidates)
    assert passed.passed is True
    assert passed.coverage_rate == 1.0
    structured = evaluate_grounding(
        "## 办理流程\n**第一步：总部审批**\n| 情形 | 要求 |\n- 单笔金额超过50万美元的，应报总部审批。[1]",
        candidates,
    )
    assert structured.passed is True
    paragraph = evaluate_grounding(
        "团组应提前履行审批程序。单笔金额超过50万美元的，应报总部审批。[1]",
        candidates,
    )
    assert paragraph.passed is True

    uncited = evaluate_grounding("金额超过50万美元时，应报总部审批。", candidates)
    assert uncited.passed is False
    assert uncited.uncited_claims

    invented = evaluate_grounding("金额超过80万美元时，应报总部审批。[1]", candidates)
    assert invented.passed is False
    assert invented.numeric_mismatch_claims


def test_authority_requires_minimum_governance_metadata():
    item = _candidate().file
    assert authority_gaps(item) == []
    assert is_authority_verified(item) is True
    item.effective_date = None
    assert "effective_date" in authority_gaps(item)
    assert is_authority_verified(item) is False
