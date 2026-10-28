"""Pytest fixtures — forces sqlite + mock adapters so tests need no external services."""
from __future__ import annotations

import os
import tempfile
import uuid

# Configure environment BEFORE importing the app (settings are cached).
# Use a unique DB file per test *process* so rapid back-to-back runs never
# collide on a stale/locked file left by a previous process.
_dbfile = os.path.join(tempfile.gettempdir(), f"zg_test_{uuid.uuid4().hex}.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_dbfile}"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["EMBED_PROVIDER"] = "mock"
os.environ["VECTOR_BACKEND"] = "memory"
os.environ["EMBED_DIM"] = "128"
os.environ["INGEST_ASYNC"] = "false"

import pytest_asyncio  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: E402,F401  register models
from app.db.session import SessionLocal, engine  # noqa: E402


@pytest_asyncio.fixture
async def session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as s:
        yield s
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
