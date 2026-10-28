"""Runnable 100-question retrieval smoke suite (not a human gold answer set)."""
from __future__ import annotations

import json
from pathlib import Path

from app.services.rag.retriever import RetrieverService

_BENCHMARK_PATH = Path(__file__).resolve().parents[3] / "tests" / "golden_qa.json"


def load_retrieval_benchmark() -> list[dict]:
    if not _BENCHMARK_PATH.is_file():
        return []
    with _BENCHMARK_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, list) else []


async def run_retrieval_benchmark(session, user, permissions) -> dict:
    """Check whether an expected regulation family appears in top-5 results."""
    retriever = RetrieverService()
    rows: list[dict] = []
    for case in load_retrieval_benchmark():
        results = await retriever.retrieve(
            session, user, permissions, case["question"], top_k=5, min_score=0.0
        )
        titles = list(dict.fromkeys(item.file.title for item in results))
        expected = case.get("expect") or []
        passed = any(keyword in title for keyword in expected for title in titles)
        rows.append(
            {
                "category": case.get("category"),
                "question": case["question"],
                "passed": passed,
                "titles": titles,
            }
        )
    total = len(rows)
    passed = sum(1 for row in rows if row["passed"])
    return {
        "suite": "retrieval_smoke_v1",
        "assurance": "source-family smoke test; not human-approved answer ground truth",
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "failures": [row for row in rows if not row["passed"]],
    }
