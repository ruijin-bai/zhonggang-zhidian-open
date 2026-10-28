from app.services.eval.business_golden import evaluate_case, summarize, validate_golden_cases


def _case():
    return {
        "id": "G001", "category": "境外审批", "question": "50万美元由谁审批？",
        "facts": {"currency": "USD"},
        "expected_sources": [{"regulation_code": "ZG-001", "clause_no": "第12条"}],
        "expected_claims": ["总部审批"], "expected_numbers": ["500000"],
        "expected_need_human": False, "expected_answer_mode": "authoritative",
        "reviewer": "BIZ-01", "reviewed_at": "2026-08-23",
    }


def test_business_golden_metrics_are_source_claim_and_number_aware():
    case = _case()
    actual = {
        "answer_interpret": "达到500000美元时须报总部审批。[1]",
        "citations": [{"regulation_code": "ZG-001", "clause_no": "第12条", "consistent": True}],
        "need_human": False, "grounding_passed": True, "authority_verified": True,
        "latency_total_ms": 1200,
    }
    row = evaluate_case(case, actual)
    result = summarize([row])
    assert row["business_answer_pass"] is True
    assert result["business_answer_accuracy"] == 1.0
    assert result["citation_precision"] == 1.0
    assert result["permission_leakage_rate"] is None


def test_business_golden_requires_expert_signoff_and_does_not_invent_empty_metrics():
    broken = _case() | {"reviewer": ""}
    assert validate_golden_cases([broken])
    result = summarize([])
    assert result["expert_reviewed_total"] == 0
    assert result["business_answer_accuracy"] is None
