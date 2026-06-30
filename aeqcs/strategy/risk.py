"""Risk metrics used by monitoring and backtests."""

from __future__ import annotations

from decimal import Decimal


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
