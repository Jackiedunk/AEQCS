"""Execution assumptions for deterministic backtests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Fill:
    date: date
    symbol: str
    quantity: int
    price: Decimal
    fee: Decimal = Decimal("0")


def shares_for_target(cash: Decimal, target_weight: float, price: Decimal, lot_size: int = 100) -> int:
    gross = cash * Decimal(str(target_weight))
    raw = int(gross / price)
    return (raw // lot_size) * lot_size
