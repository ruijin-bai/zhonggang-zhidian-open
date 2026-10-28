from app.services.rag.grounding import (
    GroundingReport,
    _verified_derived_numbers,
    passes_numeric_guard,
    requires_strict_numeric_grounding,
)
from app.services.rag.query_intent import INTENT_CALCULATION, classify_intent


def test_duration_question_is_high_risk_calculation() -> None:
    question = "M2到M5最短时间"
    assert classify_intent(question) == INTENT_CALCULATION
    assert requires_strict_numeric_grounding(question) is True


def test_valid_addition_is_accepted_as_derived_number() -> None:
    assert "7年" in _verified_derived_numbers("最短为 7年（3+1+2+1=7年）[1]")


def test_invalid_addition_does_not_pass_numeric_guard() -> None:
    assert "6年" not in _verified_derived_numbers("错误结论 6年（3+1+2+1=6年）[1]")


def test_numeric_guard_allows_reviewable_prose_only_when_numbers_match() -> None:
    report = GroundingReport(
        passed=False,
        claim_count=10,
        covered_claim_count=8,
        coverage_rate=0.8,
        invalid_citation_indices=[],
        numeric_mismatch_claims=[],
        uncited_claims=["一条非数值说明"],
        referenced_indices=[1],
    )
    assert passes_numeric_guard(report) is True
    report.numeric_mismatch_claims = ["3+1+2+1=6年"]
    assert passes_numeric_guard(report) is False
