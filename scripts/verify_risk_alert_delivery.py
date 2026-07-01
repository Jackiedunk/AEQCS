"""Verify deterministic risk alert delivery against PostgreSQL event bus."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Any
from uuid import uuid4

import asyncpg

from aeqcs.core.event_bus import EventBus
from aeqcs.core.mcp_server import normalize_asyncpg_dsn
from aeqcs.runtime.risk_alerts import publish_strategy_risk_alerts


CONSUMER_ID = "risk_alert_delivery_rehearsal"


def build_alert_report() -> dict[str, Any]:
    return {
        "alerts": [
            {
                "severity": "red",
                "action": "risk_officer.reduce_exposure",
                "metric": "gross_exposure",
                "value": "1.2",
                "threshold": "1",
            }
        ]
    }


def expected_alert_event_id(source: str) -> str:
    return f"risk_alert:{source}:risk_officer.reduce_exposure:gross_exposure"


def evaluate_delivery(
    *,
    event_id: str,
    notification_payload: dict[str, Any],
    stored_payload: dict[str, Any],
    handled_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    handled_count = len(handled_payloads)
    ok = (
        notification_payload == {"event_id": event_id, "channel": "risk_alerts"}
        and stored_payload.get("event_id") == event_id
        and stored_payload.get("type") == "risk_officer.reduce_exposure"
        and stored_payload.get("severity") == "red"
        and handled_count == 1
        and handled_payloads[0].get("event_id") == event_id
    )
    return {
        "status": "ok" if ok else "failed",
        "event_id": event_id,
        "channel": notification_payload.get("channel"),
        "handled_count": handled_count,
    }


async def run_delivery_rehearsal(dsn: str) -> dict[str, Any]:
    source = f"delivery-rehearsal-{uuid4().hex}"
    event_id = expected_alert_event_id(source)
    pool = await asyncpg.create_pool(normalize_asyncpg_dsn(dsn), min_size=1, max_size=2)
    bus = EventBus(pool)
    received_notification = asyncio.get_running_loop().create_future()
    listener_conn = await pool.acquire()

    def on_notify(_connection: Any, _pid: int, _channel: str, payload: str) -> None:
        if not received_notification.done():
            received_notification.set_result(payload)

    try:
        await listener_conn.add_listener("risk_alerts", on_notify)
        await publish_strategy_risk_alerts(
            bus,
            build_alert_report(),
            source=source,
            timestamp=datetime.utcnow(),
        )
        notify_payload_text = await asyncio.wait_for(received_notification, timeout=5)
    finally:
        await listener_conn.remove_listener("risk_alerts", on_notify)
        await pool.release(listener_conn)

    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT payload
                FROM event_log
                WHERE event_id=$1
                """,
                event_id,
            )
        handled_payloads: list[dict[str, Any]] = []

        async def handler(event_payload: dict[str, Any]) -> None:
            handled_payloads.append(event_payload)

        await bus.dispatch_notification(notify_payload_text, handler, consumer_id=CONSUMER_ID)
        await bus.dispatch_notification(notify_payload_text, handler, consumer_id=CONSUMER_ID)
        stored_payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else dict(row["payload"])
        return evaluate_delivery(
            event_id=event_id,
            notification_payload=json.loads(notify_payload_text),
            stored_payload=stored_payload,
            handled_payloads=handled_payloads,
        )
    finally:
        await pool.close()


async def _main() -> int:
    dsn = os.environ.get("AEQCS_ALERT_PG_DSN") or os.environ.get("AEQCS_CORE_PG_DSN")
    if not dsn:
        print("AEQCS_ALERT_PG_DSN or AEQCS_CORE_PG_DSN is required", file=sys.stderr)
        return 2
    report = await run_delivery_rehearsal(dsn)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, default=str))
    return 0 if report["status"] == "ok" else 1


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
