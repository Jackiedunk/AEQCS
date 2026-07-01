"""PostgreSQL LISTEN/NOTIFY event bus wrapper."""

from __future__ import annotations

import json
import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from aeqcs.core.events import Event

EventHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class EventBus:
    def __init__(self, pool: Any) -> None:
        self.pool = pool
        self._seen_event_ids: set[str] = set()

    async def publish(self, channel: str, event: Event) -> None:
        payload = json.dumps(event.to_dict(), ensure_ascii=False, default=str)
        notify_payload = json.dumps(
            {"event_id": event.event_id, "channel": channel},
            ensure_ascii=False,
            default=str,
        )
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
                await conn.execute("SELECT pg_notify($1, $2)", channel, notify_payload)

    async def dispatch_notification(
        self,
        payload: str,
        handler: EventHandler,
        *,
        consumer_id: str | None = None,
    ) -> None:
        reference = json.loads(payload)
        event_id = str(reference["event_id"])
        if event_id in self._seen_event_ids:
            return
        async with self.pool.acquire() as conn:
            if consumer_id is not None:
                claimed = await conn.fetchval(
                    """
                    INSERT INTO event_consumptions (event_id, consumer_id, consumed_ts)
                    VALUES ($1, $2, CURRENT_TIMESTAMP)
                    ON CONFLICT (event_id, consumer_id) DO NOTHING
                    RETURNING event_id
                    """,
                    event_id,
                    consumer_id,
                )
                if claimed is None:
                    return
            row = await conn.fetchrow(
                """
                SELECT payload
                FROM event_log
                WHERE event_id=$1
                """,
                event_id,
            )
        if not row:
            return
        event_payload = row["payload"]
        event = json.loads(event_payload) if isinstance(event_payload, str) else dict(event_payload)
        await handler(event)
        self._seen_event_ids.add(event_id)

    async def subscribe(
        self,
        channels: list[str],
        handler: EventHandler,
        *,
        heartbeat_interval: float = 30.0,
        reconnect_delay: float = 5.0,
    ) -> None:
        while True:
            try:
                await self._subscribe_once(channels, handler, heartbeat_interval=heartbeat_interval)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(reconnect_delay)

    async def _subscribe_once(
        self,
        channels: list[str],
        handler: EventHandler,
        *,
        heartbeat_interval: float,
    ) -> None:
        conn = await self.pool.acquire()
        listeners: list[tuple[str, Callable[..., None]]] = []
        try:
            for channel in channels:
                callback = self._build_listener_callback(handler)
                await conn.add_listener(channel, callback)
                listeners.append((channel, callback))
            while True:
                await conn.execute("SELECT 1")
                await asyncio.sleep(heartbeat_interval)
        finally:
            for channel, callback in listeners:
                await conn.remove_listener(channel, callback)
            await self.pool.release(conn)

    def _build_listener_callback(self, handler: EventHandler) -> Callable[..., None]:
        def callback(_connection: Any, _pid: int, _channel: str, payload: str) -> None:
            asyncio.create_task(self.dispatch_notification(payload, handler))

        return callback
