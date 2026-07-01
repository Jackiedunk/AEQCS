"""Publish deterministic strategy risk reports to the core event bus."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from aeqcs.core.events import RiskAlert


async def publish_strategy_risk_alerts(
    bus: Any,
    report: dict[str, Any],
    *,
    source: str,
    timestamp: datetime | None = None,
) -> None:
    event_ts = timestamp or datetime.utcnow()
    for alert in report.get("alerts", []):
        action = str(alert["action"])
        if not action.startswith("risk_officer."):
            raise ValueError(f"unsupported risk alert action: {action}")

        event = RiskAlert(
            event_id=_event_id(source, action, alert),
            timestamp=event_ts,
            knowledge_ts=event_ts,
            type=action,
            message=_message(source, action, alert),
            severity=str(alert.get("severity", "important")),
        )
        await bus.publish("risk_alerts", event)


def _event_id(source: str, action: str, alert: dict[str, Any]) -> str:
    suffix = alert.get("date") or alert.get("metric") or alert.get("symbol") or "alert"
    return f"risk_alert:{source}:{action}:{_format_value(suffix)}"


def _message(source: str, action: str, alert: dict[str, Any]) -> str:
    parts = [f"{source}: {action}"]
    for key in ("date", "metric", "symbol", "drawdown", "value", "threshold"):
        if key in alert:
            parts.append(f"{key}={_format_value(alert[key])}")
    return " ".join(parts)


def _format_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)
