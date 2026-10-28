"""Build the governed V2 retrieval-unit vector index."""
from __future__ import annotations

import argparse
import asyncio
import json

from app.db.session import SessionLocal, engine
from app.services.assets.retrieval_index import build_retrieval_embeddings
from app.services.model_runtime import load_runtime_model_config


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="建立复合制度资产 V2 问答向量索引")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        await load_runtime_model_config()
        async with SessionLocal() as session:
            result = await build_retrieval_embeddings(
                session,
                batch_size=max(1, args.batch_size),
                concurrency=max(1, min(args.concurrency, 8)),
                force=args.force,
                limit=args.limit,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main_async())
