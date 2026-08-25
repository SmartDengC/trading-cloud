from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()
DATABASE_CONNECT_TIMEOUT_SECONDS = 5
DATABASE_POOL_SIZE = 5
DATABASE_MAX_OVERFLOW = 2
DATABASE_POOL_TIMEOUT_SECONDS = 5
DATABASE_POOL_RECYCLE_SECONDS = 300

engine = create_async_engine(
    settings.database_url,
    connect_args={"connect_timeout": DATABASE_CONNECT_TIMEOUT_SECONDS},
    max_overflow=DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=DATABASE_POOL_RECYCLE_SECONDS,
    pool_size=DATABASE_POOL_SIZE,
    pool_timeout=DATABASE_POOL_TIMEOUT_SECONDS,
)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
