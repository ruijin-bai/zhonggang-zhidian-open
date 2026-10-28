"""Fail-closed verification for the real model runtime and QA chain.

Examples:
    python -m scripts.verify_model_runtime
    python -m scripts.verify_model_runtime --qa-runs 10 --output model_runtime_verification.json

The report never contains credentials, provider response bodies or base URLs.
Mock adapters fail by default; ``--allow-mock`` exists only for local diagnostics.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
import time
from pathlib import Path

from sqlalchemy import select

from app.adapters.embedding.factory import get_embedding_adapter
from app.adapters.llm.factory import get_llm_adapter
from app.adapters.reranker.factory import get_reranker_adapter
from app.db.models.clause import Clause
from app.db.models.user import User
from app.db.session import SessionLocal, dispose_engine
from app.services.auth.auth_service import get_user_permissions
from app.services.qa_service import QAService

# Reasoning models may spend dozens of completion tokens before emitting the
# final two-character answer. A tiny budget creates a false empty-response FAIL.
_SYNTHETIC_LLM_MAX_TOKENS = 256


def _safe_error(exc: Exception) -> str:
    """Return only a stable exception class; provider details may contain secrets."""
    return type(exc).__name__[:64]


def _provider_check(adapter, *, allow_mock: bool) -> tuple[bool, str]:
    kind = getattr(adapter, "kind", "unknown") if adapter is not None else "unconfigured"
    return (adapter is not None and (allow_mock or kind != "mock"), kind)


async def run_verification(
    *, qa_runs: int, component_runs: int, question: str, allow_mock: bool,
) -> dict:
    # Standalone maintenance processes do not run FastAPI startup hooks; load
    # the encrypted DB-backed R4 configuration before adapter factories.
    from app.services.model_runtime import load_runtime_model_config

    await load_runtime_model_config()
    checks: dict[str, dict] = {}
    llm = get_llm_adapter(fast=False)
    fast_llm = get_llm_adapter(fast=True)
    embedding = get_embedding_adapter()
    reranker = get_reranker_adapter()

    async def llm_check(name: str, adapter) -> None:
        allowed, kind = _provider_check(adapter, allow_mock=allow_mock)
        attempts: list[dict] = []
        for index in range(component_runs):
            started = time.perf_counter()
            try:
                if not allowed:
                    raise RuntimeError("real_provider_required")
                result = await adapter.chat(
                    [{"role": "user", "content": "仅回复OK"}],
                    temperature=0,
                    max_tokens=_SYNTHETIC_LLM_MAX_TOKENS,
                    timeout=8,
                )
                passed = bool((result.content or "").strip())
                attempts.append({
                    "run": index + 1,
                    "status": "PASS" if passed else "FAIL",
                    "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                    **({"error_code": "EmptyModelResponse"} if not passed else {}),
                })
            except Exception as exc:  # noqa: BLE001
                attempts.append({
                    "run": index + 1, "status": "FAIL", "error_code": _safe_error(exc),
                })
        checks[name] = {
            "status": "PASS" if all(item["status"] == "PASS" for item in attempts) else "FAIL",
            "provider_kind": kind,
            "runs": attempts,
        }

    await llm_check("LLM", llm)
    await llm_check("FAST_LLM", fast_llm)

    allowed, kind = _provider_check(embedding, allow_mock=allow_mock)
    embed_attempts: list[dict] = []
    for index in range(component_runs):
        started = time.perf_counter()
        try:
            if not allowed:
                raise RuntimeError("real_provider_required")
            vectors = embedding.embed(["中港智典模型运行验收"])
            dim = len(vectors[0]) if vectors and vectors[0] else 0
            passed = dim > 0 and dim == int(getattr(embedding, "dim", dim))
            embed_attempts.append({
                "run": index + 1, "status": "PASS" if passed else "FAIL",
                "vector_dim": dim,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            })
        except Exception as exc:  # noqa: BLE001
            embed_attempts.append({
                "run": index + 1, "status": "FAIL", "error_code": _safe_error(exc),
            })
    checks["EMBEDDING"] = {
        "status": "PASS" if all(item["status"] == "PASS" for item in embed_attempts) else "FAIL",
        "provider_kind": kind,
        "runs": embed_attempts,
    }

    allowed, kind = _provider_check(reranker, allow_mock=allow_mock)
    rerank_attempts: list[dict] = []
    for index in range(component_runs):
        started = time.perf_counter()
        try:
            if not allowed:
                raise RuntimeError("real_provider_required")
            ranked = await reranker.rerank(
                "审批权限", ["天气信息", "审批权限由总部负责"], top_n=2,
            )
            passed = bool(ranked) and ranked[0][0] == 1
            rerank_attempts.append({
                "run": index + 1, "status": "PASS" if passed else "FAIL",
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            })
        except Exception as exc:  # noqa: BLE001
            rerank_attempts.append({
                "run": index + 1, "status": "FAIL", "error_code": _safe_error(exc),
            })
    checks["RERANKER"] = {
        "status": "PASS" if all(item["status"] == "PASS" for item in rerank_attempts) else "FAIL",
        "provider_kind": kind,
        "runs": rerank_attempts,
    }

    async with SessionLocal() as session:
        try:
            dimension_counts = Counter(
                len(vector)
                for vector in (await session.execute(select(Clause.embedding).where(Clause.status == "current", Clause.embedding.isnot(None)))).scalars()
                if vector
            )
            dimensions = set(dimension_counts)
            expected_dim = int(getattr(embedding, "dim", 0))
            vector_pass = bool(dimensions) and dimensions == {expected_dim}
            checks["VECTOR_DIM"] = {
                "status": "PASS" if vector_pass else "FAIL",
                "expected_dim": expected_dim,
                "observed_dims": sorted(dimensions),
                "observed_dim_counts": {str(dim): dimension_counts[dim] for dim in sorted(dimension_counts)},
            }
        except Exception as exc:  # noqa: BLE001
            checks["VECTOR_DIM"] = {"status": "FAIL", "error_code": _safe_error(exc)}

        user = (
            await session.execute(select(User).where(User.role == "R4", User.is_active.is_(True)).limit(1))
        ).scalar_one_or_none()
        qa_details: list[dict] = []
        if qa_runs == 0:
            checks["QA_SMOKE"] = {
                "status": "SKIP", "reason": "synthetic_connectivity_only_no_internal_clause_egress", "runs": [],
            }
        elif user is None:
            checks["QA_SMOKE"] = {"status": "FAIL", "error_code": "NoActiveR4User", "runs": qa_details}
        else:
            permissions = await get_user_permissions(session, user)
            for index in range(qa_runs):
                started = time.perf_counter()
                try:
                    result = await QAService().ask(
                        session, user=user, permissions=permissions, question=question,
                        round_no=2, is_evaluation=True,
                    )
                    passed = bool(result.get("answer_interpret")) and bool(result.get("citations"))
                    qa_details.append({
                        "run": index + 1, "status": "PASS" if passed else "FAIL",
                        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                        "degraded": bool(result.get("degraded")),
                        "need_human": bool(result.get("need_human")),
                    })
                except Exception as exc:  # noqa: BLE001
                    await session.rollback()
                    qa_details.append({"run": index + 1, "status": "FAIL", "error_code": _safe_error(exc)})
            checks["QA_SMOKE"] = {
                "status": "PASS" if len(qa_details) == qa_runs and all(row["status"] == "PASS" for row in qa_details) else "FAIL",
                "runs": qa_details,
            }
    component_names = ("LLM", "FAST_LLM", "EMBEDDING", "RERANKER", "VECTOR_DIM")
    component_checks_passed = all(checks[name]["status"] == "PASS" for name in component_names)
    qa_chain_passed = checks["QA_SMOKE"]["status"] == "PASS"
    return {
        "all_passed": component_checks_passed and qa_chain_passed,
        "component_checks_passed": component_checks_passed,
        "qa_chain_passed": qa_chain_passed,
        "component_runs": component_runs,
        "real_provider_required": not allow_mock,
        "checks": checks,
        "security": "credentials_and_provider_bodies_omitted",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--qa-runs", type=int, default=1, choices=range(0, 11),
        help="0仅做合成文本模型连通性，不发送内部制度条款；正式QA链使用1-10",
    )
    parser.add_argument(
        "--component-runs", type=int, default=1, choices=range(1, 11),
        help="LLM、快速模型、Embedding和Reranker合成稳定性连续运行1-10次",
    )
    parser.add_argument("--question", default="员工借调需要履行哪些审批手续？")
    parser.add_argument("--output", default="model_runtime_verification.json")
    parser.add_argument("--allow-mock", action="store_true", help="仅用于本地诊断；报告会显式标记")
    args = parser.parse_args()
    async def run_and_cleanup() -> dict:
        try:
            return await run_verification(
                qa_runs=args.qa_runs,
                component_runs=args.component_runs,
                question=args.question,
                allow_mock=args.allow_mock,
            )
        finally:
            await dispose_engine()

    result = asyncio.run(run_and_cleanup())
    output = Path(args.output).resolve()
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, item in result["checks"].items():
        print(f"{name}: {item['status']}")
    print(f"REPORT: {output}")
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
