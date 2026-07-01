"""Risk metrics used by monitoring and backtests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, TypedDict


class DrawdownAlert(TypedDict):
    date: date
    severity: Literal["warn", "red"]
    action: Literal["risk_officer.review_drawdown", "risk_officer.reduce_risk"]
    drawdown: Decimal
    threshold: Decimal


class DrawdownRiskReport(TypedDict):
    status: Literal["ok", "warn", "red"]
    max_drawdown: Decimal
    alerts: list[DrawdownAlert]


def drawdown(nav: list[Decimal]) -> list[Decimal]:
    peak = Decimal("0")
    values: list[Decimal] = []
    for point in nav:
        peak = max(peak, point)
        values.append((point / peak - Decimal("1")) if peak else Decimal("0"))
    return values


def max_drawdown_decimal(nav: list[Decimal]) -> Decimal:
    values = drawdown(nav)
    return min(values) if values else Decimal("0")


def _require_non_negative_finite_threshold(value: Decimal, name: str) -> Decimal:
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def scan_drawdown_risk(
    nav: list[tuple[date, Decimal]],
    *,
    warn_threshold: Decimal = Decimal("0.05"),
    red_threshold: Decimal = Decimal("0.10"),
) -> DrawdownRiskReport:
    warn_threshold = _require_non_negative_finite_threshold(warn_threshold, "warn_threshold")
    red_threshold = _require_non_negative_finite_threshold(red_threshold, "red_threshold")
    if red_threshold < warn_threshold:
        raise ValueError("red_threshold must be greater than or equal to warn_threshold")

    peak = Decimal("0")
    max_drawdown = Decimal("0")
    alerts: list[DrawdownAlert] = []
    warn_sent = False
    red_sent = False

    for day, point in nav:
        peak = max(peak, point)
        current_drawdown = (point / peak - Decimal("1")) if peak else Decimal("0")
        max_drawdown = min(max_drawdown, current_drawdown)

        if not red_sent and current_drawdown <= -red_threshold:
            alerts.append(
                {
                    "date": day,
                    "severity": "red",
                    "action": "risk_officer.reduce_risk",
                    "drawdown": current_drawdown,
                    "threshold": red_threshold,
                }
            )
            red_sent = True
            continue

        if not warn_sent and current_drawdown <= -warn_threshold:
            alerts.append(
                {
                    "date": day,
                    "severity": "warn",
                    "action": "risk_officer.review_drawdown",
                    "drawdown": current_drawdown,
                    "threshold": warn_threshold,
                }
            )
            warn_sent = True

    status: Literal["ok", "warn", "red"] = "ok"
    if max_drawdown <= -red_threshold:
        status = "red"
    elif max_drawdown <= -warn_threshold:
        status = "warn"

    return {
        "status": status,
        "max_drawdown": max_drawdown,
        "alerts": alerts,
    }
