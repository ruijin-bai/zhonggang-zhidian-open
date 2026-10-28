"""Async SQLAlchemy engine and session factory."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession

from app.core.config import get_settings

_settings = get_settings()


def _create_engine():
    url = _settings.DATABASE_URL
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_async_engine(
        url,
        echo=_settings.DB_ECHO,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


engine = _create_engine()
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """FastAPI dependency yielding an async session."""
    async with SessionLocal() as session:
        yield session


async def dispose_engine() -> None:
    await engine.dispose()
