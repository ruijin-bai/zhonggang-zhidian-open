"""Expert-reviewed business QA metrics; deliberately separate from smoke recall."""
from __future__ import annotations

import re
from statistics import median


def _norm(value: object) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * quantile)))
    return round(float(ordered[index]), 1)


def validate_golden_cases(cases: list[dict]) -> list[str]:
    errors: list[str] = []
    required = {
        "id", "category", "question", "facts", "expected_sources", "expected_claims",
        "expected_numbers", "expected_need_human", "expected_answer_mode", "reviewer", "reviewed_at",
    }
    seen: set[str] = set()
    for index, case in enumerate(cases):
        prefix = f"case[{index}]"
        missing = sorted(required - set(case))
        if missing:
            errors.append(f"{prefix} missing: {', '.join(missing)}")
            continue
        case_id = str(case["id"])
        if not re.fullmatch(r"G\d{3,}", case_id):
            errors.append(f"{prefix} id invalid")
        if case_id in seen:
            errors.append(f"{prefix} id duplicate")
        seen.add(case_id)
        if not str(case["reviewer"]).strip() or not str(case["reviewed_at"]).strip():
            errors.append(f"{prefix} requires business reviewer and reviewed_at")
        for source in case["expected_sources"]:
            if not source.get("regulation_code") or not source.get("clause_no"):
                errors.append(f"{prefix} expected source lacks regulation_code/clause_no")
    return errors


def evaluate_case(case: dict, actual: dict) -> dict:
    answer = actual.get("answer_interpret") or actual.get("answer") or ""
    actual_sources = {
        (str(item.get("regulation_code", "")).strip(), str(item.get("clause_no", "")).strip())
        for item in actual.get("citations", [])
        if item.get("consistent") and item.get("regulation_code") and item.get("clause_no")
    }
    expected_sources = {
        (str(item["regulation_code"]).strip(), str(item["clause_no"]).strip())
        for item in case.get("expected_sources", [])
    }
    source_hits = actual_sources & expected_sources
    claims = [str(value) for value in case.get("expected_claims", [])]
    numbers = [str(value) for value in case.get("expected_numbers", [])]
    claim_hits = [value for value in claims if _norm(value) in _norm(answer)]
    number_hits = [value for value in numbers if _norm(value) in _norm(answer)]
    expected_need_human = bool(case.get("expected_need_human"))
    actual_need_human = bool(actual.get("need_human"))
    refusal_match = expected_need_human == actual_need_human
    retrieval_recall = len(source_hits) / len(expected_sources) if expected_sources else None
    citation_precision = len(source_hits) / len(actual_sources) if actual_sources else (1.0 if not expected_sources else 0.0)
    citation_recall = len(source_hits) / len(expected_sources) if expected_sources else None
    claim_rate = len(claim_hits) / len(claims) if claims else 1.0
    numeric_fidelity = len(number_hits) / len(numbers) if numbers else 1.0
    authority_pass = bool(actual.get("authority_verified")) if case.get("expected_answer_mode") == "authoritative" else True
    grounding_pass = bool(actual.get("grounding_passed")) and claim_rate == 1.0 if claims else bool(actual.get("grounding_passed"))
    business_answer_pass = all((claim_rate == 1.0, numeric_fidelity == 1.0, refusal_match, authority_pass))
    return {
        "id": case["id"],
        "category": case["category"],
        "retrieval_recall": retrieval_recall,
        "citation_precision": citation_precision,
        "citation_recall": citation_recall,
        "claim_grounding_rate": claim_rate,
        "numeric_fidelity": numeric_fidelity,
        "authority_pass": authority_pass,
        "refusal_match": refusal_match,
        "grounding_pass": grounding_pass,
        "business_answer_pass": business_answer_pass,
        "permission_probe": bool(actual.get("permission_probe")),
        "permission_leaked": bool(actual.get("permission_leaked")),
        "latency_first_token_ms": actual.get("latency_first_token_ms"),
        "latency_total_ms": actual.get("latency_total_ms"),
    }


def summarize(rows: list[dict]) -> dict:
    def average(key: str) -> float | None:
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        return round(sum(values) / len(values), 4) if values else None

    def pass_rate(key: str) -> float | None:
        return round(sum(bool(row.get(key)) for row in rows) / len(rows), 4) if rows else None

    permission_probes = [row for row in rows if row.get("permission_probe")]
    first = [float(row["latency_first_token_ms"]) for row in rows if row.get("latency_first_token_ms") is not None]
    total = [float(row["latency_total_ms"]) for row in rows if row.get("latency_total_ms") is not None]
    return {
        "dataset": "golden_business_qa",
        "metric_scope": "business_answer_quality",
        "expert_reviewed_total": len(rows),
        "business_answer_accuracy": pass_rate("business_answer_pass"),
        "retrieval_recall": average("retrieval_recall"),
        "citation_precision": average("citation_precision"),
        "citation_recall": average("citation_recall"),
        "claim_grounding_rate": average("claim_grounding_rate"),
        "numeric_fidelity": average("numeric_fidelity"),
        "authority_pass_rate": pass_rate("authority_pass"),
        "refusal_accuracy": pass_rate("refusal_match"),
        "permission_leakage_rate": (
            round(sum(bool(row.get("permission_leaked")) for row in permission_probes) / len(permission_probes), 4)
            if permission_probes else None
        ),
        "p50_first_token_ms": round(median(first), 1) if first else None,
        "p95_first_token_ms": _percentile(first, 0.95),
        "p50_total_ms": round(median(total), 1) if total else None,
        "p95_total_ms": _percentile(total, 0.95),
        "details": rows,
        "disclaimer": "仅业务专家签审的 golden 集可用于业务答案准确率；smoke recall 不得替代本指标。",
    }
