from app.utils.metrics import metrics_payload


def test_required_competition_observability_metrics_are_registered():
    payload = metrics_payload().decode("utf-8")
    for name in (
        "qa_requests_total", "qa_completed_total", "qa_need_human_total", "zg_qa_degraded_total",
        "qa_grounding_failed_total", "qa_authority_unverified_total",
        "qa_first_token_latency_seconds", "qa_total_latency_seconds",
        "qa_retrieval_latency_seconds", "qa_generation_latency_seconds",
        "ingestion_jobs_total", "ingestion_failed_total", "parse_quality_score", "parse_backend_total",
        "active_rule_total", "rule_conflict_total", "manual_review_total",
    ):
        assert name in payload
