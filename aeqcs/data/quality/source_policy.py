"""Data source health response policy."""

from __future__ import annotations

from typing import Any


PRIMARY_ROLES = {"daily", "financial", "minute"}
CROSS_CHECK_ROLES = {"daily_cross_check"}


def decide_source_health_action(health_report: dict[str, Any], *, role: str) -> dict[str, str]:
    status = str(health_report.get("status", "error"))
    if status == "ok":
        return {"action": "continue", "severity": "info", "reason": "data source is healthy"}
    if role in PRIMARY_ROLES:
        return {
            "action": "stop_calculation",
            "severity": "red",
            "reason": f"primary {role} data source is unhealthy",
        }
    if role in CROSS_CHECK_ROLES:
        return {
            "action": "emit_alert",
            "severity": "warning",
            "reason": "cross-check data source is unhealthy",
        }
    return {
        "action": "emit_alert",
        "severity": "warning",
        "reason": f"{role} data source is unhealthy",
    }
