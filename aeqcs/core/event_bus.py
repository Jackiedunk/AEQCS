"""PostgreSQL LISTEN/NOTIFY event bus wrapper."""

from __future__ import annotations

import json
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aeqcs.core.events import Event

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def publish(self, channel: str, event: Event) -> None:
        payload = json.dumps(event.to_dict(), ensure_ascii=False, default=str)
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO event_log (event_id, channel, payload, created_ts)
                    VALUES ($1, $2, $3::jsonb, CURRENT_TIMESTAMP)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    event.event_id,
                    channel,
                    payload,
                )
                await conn.execute("SELECT pg_notify($1, $2)", channel, payload)

    async def subscribe(self, channels: list[str], handler: EventHandler) -> None:
        conn = await self.pool.acquire()
        try:
            for channel in channels:
                await conn.add_listener(
                    channel,
                    lambda _c, _p, _ch, payload: asyncio.create_task(handler(json.loads(payload))),
                )
            while True:
                await conn.execute("SELECT 1")
        finally:
            await self.pool.release(conn)
