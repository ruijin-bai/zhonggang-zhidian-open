"""Prometheus metrics for observability (NFR-05)."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, generate_latest

QA_DEGRADED_TOTAL = Counter(
    "zg_qa_degraded_total",
    "QA requests served with a controlled degradation",
    ["reason"],
)
QA_REQUESTS_TOTAL = Counter("qa_requests", "QA requests entering the governed pipeline")
QA_COMPLETED_TOTAL = Counter("qa_completed", "QA requests with a persisted answer")
QA_NEED_HUMAN_TOTAL = Counter("qa_need_human", "QA answers requiring manual review")
QA_GROUNDING_FAILED_TOTAL = Counter("qa_grounding_failed", "QA answers failing claim grounding")
QA_AUTHORITY_UNVERIFIED_TOTAL = Counter("qa_authority_unverified", "QA answers using unverified authority")
QA_FIRST_TOKEN_LATENCY_SECONDS = Histogram("qa_first_token_latency_seconds", "Seconds to first generated token")
QA_TOTAL_LATENCY_SECONDS = Histogram("qa_total_latency_seconds", "Seconds to completed QA answer")
QA_RETRIEVAL_LATENCY_SECONDS = Histogram("qa_retrieval_latency_seconds", "Seconds spent in retrieval")
QA_GENERATION_LATENCY_SECONDS = Histogram("qa_generation_latency_seconds", "Seconds spent in final generation")

INGESTION_JOBS_TOTAL = Counter("ingestion_jobs", "Claimed ingestion jobs")
INGESTION_FAILED_TOTAL = Counter("ingestion_failed", "Failed ingestion jobs")
PARSE_QUALITY_SCORE = Histogram("parse_quality_score", "Deterministic parse quality score", buckets=(0, 25, 50, 72, 85, 95, 100))
PARSE_BACKEND_TOTAL = Counter("parse_backend", "Documents parsed by backend", ["backend"])

ACTIVE_RULE_TOTAL = Gauge("active_rule_total", "Applicable governed rules in the latest evaluation")
RULE_CONFLICT_TOTAL = Counter("rule_conflict", "Rule evaluations with conflicting approval paths")
MANUAL_REVIEW_TOTAL = Counter("manual_review", "Rule evaluations transferred to manual review", ["reason"])
PUSH_TOTAL = Counter("zg_push_total", "Push notifications sent", ["status"])


def metrics_payload() -> bytes:
    return generate_latest()
