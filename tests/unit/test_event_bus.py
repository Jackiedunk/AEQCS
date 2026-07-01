import json
import asyncio
from datetime import datetime

import pytest

from aeqcs.core.event_bus import EventBus
from aeqcs.core.events import NewsEvent
from aeqcs.runtime.intraday import publish_cep_alerts


class FakeConn:
    def __init__(self) -> None:
        self.calls = []
        self.rows = {}
        self.consumer_claims = set()

    async def execute(self, query, *args):
        self.calls.append((query, args))
        return "OK"

    async def fetchrow(self, query, *args):
        self.calls.append((query, args))
        return self.rows.get(args[0])

    async def fetchval(self, query, *args):
        self.calls.append((query, args))
        if "INSERT INTO event_consumptions" in query:
            claim = (args[0], args[1])
            if claim in self.consumer_claims:
                return None
            self.consumer_claims.add(claim)
            return args[0]
        return None

    def transaction(self):
        return AcquireContext(self)


class AcquireContext:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self) -> None:
        self.conn = FakeConn()

    def acquire(self):
        return AcquireContext(self.conn)


class FakeListenConn:
    def __init__(self, execute_error=None) -> None:
        self.listeners = []
        self.removed_listeners = []
        self.wait_started = asyncio.Event()
        self.execute_error = execute_error

    async def add_listener(self, channel, callback):
        self.listeners.append((channel, callback))

    async def remove_listener(self, channel, callback):
        self.removed_listeners.append((channel, callback))

    async def execute(self, query, *args):
        self.wait_started.set()
        if self.execute_error is not None:
            raise self.execute_error
        await asyncio.sleep(3600)


class FakeListenPool:
    def __init__(self, conns=None) -> None:
        self.conns = conns or [FakeListenConn()]
        self.conn = self.conns[0]
        self.released = []
        self.acquire_count = 0

    async def acquire(self):
        conn = self.conns[self.acquire_count]
        self.acquire_count += 1
        self.conn = conn
        return conn

    async def release(self, conn):
        self.released.append(conn)


@pytest.mark.asyncio
async def test_event_bus_notifies_lightweight_reference_for_large_event_payload():
    pool = FakePool()
    bus = EventBus(pool)
    event = NewsEvent(
        event_id="news_1",
        timestamp=datetime(2026, 1, 1, 9, 30),
        knowledge_ts=datetime(2026, 1, 1, 9, 30),
        source="wire",
        level="A",
        title="large payload",
        content="x" * 9000,
    )

    await bus.publish("news_raw", event)

    insert_call = next(call for call in pool.conn.calls if "INSERT INTO event_log" in call[0])
    notify_call = next(call for call in pool.conn.calls if "pg_notify" in call[0])
    stored_payload = json.loads(insert_call[1][2])
    notify_payload = json.loads(notify_call[1][1])

    assert stored_payload["content"] == "x" * 9000
    assert notify_payload == {"event_id": "news_1", "channel": "news_raw"}
    assert len(notify_call[1][1].encode("utf-8")) < 8000


@pytest.mark.asyncio
async def test_event_bus_dispatches_lightweight_notification_by_fetching_event_log_once():
    pool = FakePool()
    pool.conn.rows["news_1"] = {
        "payload": json.dumps(
            {
                "event_id": "news_1",
                "source": "wire",
                "content": "full news body",
            }
        )
    }
    bus = EventBus(pool)
    handled = []

    async def handler(event):
        handled.append(event)

    payload = json.dumps({"event_id": "news_1", "channel": "news_raw"})
    await bus.dispatch_notification(payload, handler)
    await bus.dispatch_notification(payload, handler)

    fetch_calls = [call for call in pool.conn.calls if "FROM event_log" in call[0]]
    assert handled == [{"event_id": "news_1", "source": "wire", "content": "full news body"}]
    assert len(fetch_calls) == 1


@pytest.mark.asyncio
async def test_event_bus_dispatch_uses_db_claim_for_cross_process_consumer_id():
    pool = FakePool()
    pool.conn.rows["news_1"] = {
        "payload": json.dumps(
            {
                "event_id": "news_1",
                "source": "wire",
                "content": "full news body",
            }
        )
    }
    first_bus = EventBus(pool)
    second_bus = EventBus(pool)
    handled = []

    async def handler(event):
        handled.append(event)

    payload = json.dumps({"event_id": "news_1", "channel": "news_raw"})
    await first_bus.dispatch_notification(payload, handler, consumer_id="risk_officer")
    await second_bus.dispatch_notification(payload, handler, consumer_id="risk_officer")

    claim_calls = [call for call in pool.conn.calls if "INSERT INTO event_consumptions" in call[0]]
    assert handled == [{"event_id": "news_1", "source": "wire", "content": "full news body"}]
    assert len(claim_calls) == 2
    assert claim_calls[0][1] == ("news_1", "risk_officer")


@pytest.mark.asyncio
async def test_cep_alert_publish_uses_event_bus_lightweight_reference():
    pool = FakePool()
    bus = EventBus(pool)

    await publish_cep_alerts(
        bus,
        [
            {
                "alert_id": "cep:m1:sudden_spike",
                "event_id": "m1",
                "rule_id": "sudden_spike",
                "event_type": "market",
                "symbol": "000001",
                "priority": "urgent",
                "action": "risk_officer.flag_spike",
                "message": "Market price moved beyond the configured spike threshold",
            }
        ],
        timestamp=datetime(2026, 1, 2, 9, 31),
    )

    insert_call = next(call for call in pool.conn.calls if "INSERT INTO event_log" in call[0])
    notify_call = next(call for call in pool.conn.calls if "pg_notify" in call[0])
    stored_payload = json.loads(insert_call[1][2])
    notify_payload = json.loads(notify_call[1][1])

    assert insert_call[1][1] == "risk_alerts"
    assert stored_payload["event_id"] == "risk_alert:cep:m1:sudden_spike"
    assert stored_payload["type"] == "sudden_spike"
    assert stored_payload["severity"] == "urgent"
    assert notify_payload == {
        "event_id": "risk_alert:cep:m1:sudden_spike",
        "channel": "risk_alerts",
    }
    assert len(notify_call[1][1].encode("utf-8")) < 8000


@pytest.mark.asyncio
async def test_event_bus_subscribe_removes_listeners_and_releases_connection_on_cancel():
    pool = FakeListenPool()
    bus = EventBus(pool)

    async def handler(event):
        raise AssertionError("handler should not run without a notification")

    task = asyncio.create_task(bus.subscribe(["risk_alerts", "news_raw"], handler))
    await asyncio.wait_for(pool.conn.wait_started.wait(), timeout=1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [channel for channel, _callback in pool.conn.listeners] == ["risk_alerts", "news_raw"]
    assert pool.conn.removed_listeners == pool.conn.listeners
    assert pool.released == [pool.conn]


@pytest.mark.asyncio
async def test_event_bus_subscribe_reconnects_after_connection_error():
    first_conn = FakeListenConn(execute_error=ConnectionError("lost notify connection"))
    second_conn = FakeListenConn()
    pool = FakeListenPool([first_conn, second_conn])
    bus = EventBus(pool)

    async def handler(event):
        raise AssertionError("handler should not run without a notification")

    task = asyncio.create_task(
        bus.subscribe(
            ["risk_alerts"],
            handler,
            heartbeat_interval=0,
            reconnect_delay=0,
        )
    )
    await asyncio.wait_for(first_conn.wait_started.wait(), timeout=1)
    await asyncio.wait_for(second_conn.wait_started.wait(), timeout=1)

    assert [channel for channel, _callback in first_conn.listeners] == ["risk_alerts"]
    assert first_conn.removed_listeners == first_conn.listeners
    assert pool.released == [first_conn]
    assert [channel for channel, _callback in second_conn.listeners] == ["risk_alerts"]

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert second_conn.removed_listeners == second_conn.listeners
    assert pool.released == [first_conn, second_conn]
