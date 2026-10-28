"""Encrypt legacy plaintext model credentials in the configured database."""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.secret_vault import encrypt_secret
from app.db.models.model_config import ModelConfig
from app.db.session import SessionLocal


async def main() -> None:
    async with SessionLocal() as session:
        rows = list((await session.execute(select(ModelConfig))).scalars().all())
        changed = 0
        for row in rows:
            before = (row.llm_api_key, row.embed_api_key)
            row.llm_api_key = encrypt_secret(row.llm_api_key)
            row.embed_api_key = encrypt_secret(row.embed_api_key)
            changed += before != (row.llm_api_key, row.embed_api_key)
        await session.commit()
    print(f"MODEL_CONFIG_ENCRYPTED rows={changed}")


if __name__ == "__main__":
    asyncio.run(main())
