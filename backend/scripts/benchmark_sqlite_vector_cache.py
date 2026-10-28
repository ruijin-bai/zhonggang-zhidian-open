"""Measure cold/warm SQLite retrieval without sending any text externally."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import time

from sqlalchemy import select

from app.db.models.permission import Permission
from app.db.models.user import User
from app.db.session import SessionLocal, dispose_engine
from app.services.rag.retriever import RetrieverService, reset_memory_vector_cache


class LocalSyntheticEmbedding:
    """Deterministic 4096-d probe; never opens a network connection."""

    kind = "local_synthetic"
    dim = 4096

    def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        value = 1.0 / math.sqrt(self.dim)
        return [[value] * self.dim for _ in texts]


async def run_benchmark(runs: int) -> dict:
    reset_memory_vector_cache()
    measurements: list[dict] = []
    async with SessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.role == "R4").limit(1))
        ).scalar_one()
        permissions = list((await session.execute(
            select(Permission).where(Permission.role == user.role)
        )).scalars())
        service = RetrieverService()
        service.embed = LocalSyntheticEmbedding()
        service.reranker = None
        for run in range(1, runs + 1):
            started = time.perf_counter()
            results = await service.retrieve(
                session,
                user,
                permissions,
                "本地合成检索性能验收",
                top_k=5,
                min_score=0.0,
            )
            measurements.append({
                "run": run,
                "phase": "cold" if run == 1 else "warm",
                "result_count": len(results),
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            })
    return {
        "mode": "local_synthetic_no_external_data_egress",
        "dimension": LocalSyntheticEmbedding.dim,
        "measurements": measurements,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=2, choices=range(2, 6))
    args = parser.parse_args()

    async def execute() -> dict:
        try:
            return await run_benchmark(args.runs)
        finally:
            await dispose_engine()

    print(json.dumps(asyncio.run(execute()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
