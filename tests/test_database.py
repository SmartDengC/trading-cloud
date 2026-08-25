from app.database import (
    DATABASE_CONNECT_TIMEOUT_SECONDS,
    DATABASE_MAX_OVERFLOW,
    DATABASE_POOL_RECYCLE_SECONDS,
    DATABASE_POOL_SIZE,
    DATABASE_POOL_TIMEOUT_SECONDS,
    engine,
)


def test_database_engine_uses_bounded_pool_settings() -> None:
    assert DATABASE_CONNECT_TIMEOUT_SECONDS == 5
    assert engine.pool.size() == DATABASE_POOL_SIZE == 5  # type: ignore[attr-defined]
    assert engine.pool.timeout() == DATABASE_POOL_TIMEOUT_SECONDS == 5  # type: ignore[attr-defined]
    assert engine.pool._max_overflow == DATABASE_MAX_OVERFLOW == 2  # type: ignore[attr-defined]
    assert engine.pool._recycle == DATABASE_POOL_RECYCLE_SECONDS == 300
