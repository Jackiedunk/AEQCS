"""Intraday monitor entrypoint and deterministic CEP rules."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from aeqcs.core.events import RiskAlert


INTRADAY_PG_CONNECTIONS = 4
ALLOWED_ACTION_PREFIXES = ("risk_officer.", "data_steward.")
CepMatcher = Callable[[dict[str, Any], list[dict[str, Any]]], bool]


def load_cep_rules(path: str | Path = "aeqcs/config/cep_rules.yaml") -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh) or {}
    rules = list(loaded.get("rules", []))
    for rule in rules:
        action = str(rule["action"])
        if not action.startswith(ALLOWED_ACTION_PREFIXES):
            raise ValueError(f"unsupported CEP action role: {action}")
        condition = str(rule.get("condition", ""))
        if ("high_limit" in condition or "low_limit" in condition) and rule.get("price_basis") != "raw":
            raise ValueError(f"CEP rule {rule.get('id')} uses limit prices and must declare price_basis: raw")
    return rules


def scan_cep_events(events: list[dict[str, Any]], rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    supported_rules: dict[str, CepMatcher] = {
        "sudden_spike": _match_sudden_spike,
        "s_level_news": _match_s_level_news,
        "limit_up_open": _match_limit_up_open,
        "sector_linkage": _match_sector_linkage,
        "volume_breakout": _match_volume_breakout,
        "portfolio_drawdown": _match_portfolio_drawdown,
    }
    for event in events:
        _validate_event_identity(event)
        for rule in rules:
            matcher = supported_rules.get(str(rule["id"]))
            if matcher is None or not matcher(event, events):
                continue
            alerts.append(_alert_from_event(event, rule))
    return alerts


def _match_sudden_spike(event: dict[str, Any], _events: list[dict[str, Any]]) -> bool:
    if event.get("event_type") != "market":
        return False
    pre_close = _optional_float(event, "pre_close")
    if pre_close <= 0:
        return False
    close = _required_float(event, "close")
    return abs(close / pre_close - 1) > 0.05


def _match_s_level_news(event: dict[str, Any], _events: list[dict[str, Any]]) -> bool:
    return event.get("event_type") == "news" and event.get("level") == "S"


def _match_limit_up_open(event: dict[str, Any], _events: list[dict[str, Any]]) -> bool:
    if event.get("event_type") != "market":
        return False
    return event.get("tick_status") == "OPEN" and abs(
        _required_float(event, "close") - _required_float(event, "high_limit")
    ) < 1e-3


def _match_sector_linkage(event: dict[str, Any], events: list[dict[str, Any]]) -> bool:
    if event.get("event_type") != "market" or _optional_float(event, "change_pct") <= 0.03:
        return False
    concept = event.get("concept")
    if not concept:
        return False

    event_ts = event.get("timestamp")
    linked = [
        candidate
        for candidate in events
        if candidate.get("event_type") == "market"
        and candidate.get("concept") == concept
        and _optional_float(candidate, "change_pct") > 0.03
        and _within_minutes(candidate.get("timestamp"), event_ts, minutes=5)
    ]
    return len(linked) >= 3


def _match_volume_breakout(event: dict[str, Any], _events: list[dict[str, Any]]) -> bool:
    if event.get("event_type") != "market":
        return False
    mean_volume = _optional_float(event, "volume_mean_20")
    if mean_volume <= 0:
        mean_volume = _optional_float(event, "rolling_volume_mean_20")
    if mean_volume <= 0:
        return False
    return _optional_float(event, "volume") > 3 * mean_volume


def _match_portfolio_drawdown(event: dict[str, Any], _events: list[dict[str, Any]]) -> bool:
    if event.get("event_type") != "portfolio":
        return False
    return abs(_optional_float(event, "drawdown")) > 0.05


def _validate_event_identity(event: dict[str, Any]) -> None:
    if not isinstance(event, dict):
        raise ValueError("CEP event must be an object")
    if not str(event.get("event_id", "")).strip():
        raise ValueError("CEP event requires event_id")
    if not str(event.get("event_type", "")).strip():
        raise ValueError(f"CEP event {event['event_id']} requires event_type")


def _event_id(event: dict[str, Any]) -> str:
    return str(event.get("event_id", "<unknown>"))


def _required_float(event: dict[str, Any], field: str) -> float:
    if field not in event or event[field] in {None, ""}:
        raise ValueError(f"CEP event {_event_id(event)} requires {field}")
    return _coerce_float(event, field)


def _optional_float(event: dict[str, Any], field: str) -> float:
    if field not in event or event[field] in {None, ""}:
        return 0.0
    return _coerce_float(event, field)


def _coerce_float(event: dict[str, Any], field: str) -> float:
    try:
        return float(event[field])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"CEP event {_event_id(event)} field {field} must be numeric") from exc


def _within_minutes(left: Any, right: Any, *, minutes: int) -> bool:
    if not isinstance(left, datetime) or not isinstance(right, datetime):
        return True
    return abs((left - right).total_seconds()) <= minutes * 60


def _alert_from_event(event: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    rule_id = str(rule["id"])
    return {
        "alert_id": f"cep:{event['event_id']}:{rule_id}",
        "event_id": event["event_id"],
        "rule_id": rule_id,
        "event_type": event.get("event_type"),
        "symbol": event.get("symbol"),
        "priority": rule["priority"],
        "action": rule["action"],
        "message": _message_for(rule_id),
    }


def _message_for(rule_id: str) -> str:
    messages = {
        "sudden_spike": "Market price moved beyond the configured spike threshold",
        "s_level_news": "S-level news requires deterministic reference queueing",
        "limit_up_open": "Symbol opened at or near the high limit",
        "sector_linkage": "Concept linkage moved beyond the configured breadth threshold",
        "volume_breakout": "Volume moved beyond the configured rolling mean threshold",
        "portfolio_drawdown": "Portfolio drawdown moved beyond the configured threshold",
    }
    return messages.get(rule_id, f"CEP rule triggered: {rule_id}")


async def publish_cep_alerts(bus: Any, alerts: list[dict[str, Any]], *, timestamp: datetime | None = None) -> None:
    event_ts = timestamp or datetime.utcnow()
    for alert in alerts:
        symbol = alert.get("symbol")
        message = str(alert["message"])
        if symbol:
            message = f"{symbol}: {message}"
        event = RiskAlert(
            event_id=f"risk_alert:{alert['alert_id']}",
            timestamp=event_ts,
            knowledge_ts=event_ts,
            type=str(alert["rule_id"]),
            message=message,
            severity=str(alert["priority"]),
        )
        await bus.publish("risk_alerts", event)


def main() -> None:
    rules = load_cep_rules()
    print(f"AEQCS intraday monitor loaded {len(rules)} CEP rules")
