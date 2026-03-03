"""Database connection pool singleton."""

from __future__ import annotations

import logging
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


def init_pool() -> None:
    """Initialize the connection pool. Call once at app startup."""
    global _pool
    settings = get_settings()
    if not settings.database_url:
        logger.info("DATABASE_URL not set — running without DB pool")
        return
    _pool = ConnectionPool(
        conninfo=settings.database_url,
        min_size=2,
        max_size=10,
        kwargs={"row_factory": dict_row},
    )
    logger.info("Database connection pool initialized (min=2, max=10)")


def close_pool() -> None:
    """Close the connection pool. Call at app shutdown."""
    global _pool
    if _pool:
        _pool.close()
        _pool = None
        logger.info("Database connection pool closed")


@contextmanager
def get_connection():
    """Get a connection from the pool.

    Falls back to None if pool is not initialized.
    Usage:
        with get_connection() as conn:
            if conn is None:
                # handle no-DB case
                return
            with conn.cursor() as cur:
                cur.execute(...)
    """
    if _pool is None:
        yield None
        return
    with _pool.connection() as conn:
        yield conn


def has_pool() -> bool:
    """Check if the connection pool is available."""
    return _pool is not None
