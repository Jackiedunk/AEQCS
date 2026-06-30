"""Async PostgreSQL pool helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import asyncpg


class PgStore:
    def __init__(self, dsn: str, pool_size: int = 8) -> None:
        self.dsn = dsn
        self.pool_size = pool_size
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> asyncpg.Pool:
        self.pool = await asyncpg.create_pool(dsn=self.dsn, min_size=1, max_size=self.pool_size)
        return self.pool

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        if self.pool is None:
            await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                yield conn
