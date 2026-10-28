"""Run the 100-question retrieval smoke suite against the configured database."""
from __future__ import annotations

import asyncio
import json

from sqlalchemy import select

from app.db.models.permission import Permission
from app.db.models.user import User
from app.db.session import SessionLocal
from app.services.eval.retrieval_benchmark import run_retrieval_benchmark
from app.services.model_runtime import load_runtime_model_config


async def main() -> None:
    await load_runtime_model_config()
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.role == "R4").limit(1))).scalar_one()
        permissions = list(
            (await session.execute(select(Permission).where(Permission.role == user.role))).scalars()
        )
        result = await run_retrieval_benchmark(session, user, permissions)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
