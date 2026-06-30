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


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    fee_rate: Decimal = Decimal("0")
    min_fee: Decimal = Decimal("0")
    slippage_bps: Decimal = Decimal("0")
    lot_size: int = 100


def buy_price_with_slippage(open_price: Decimal, config: ExecutionConfig) -> Decimal:
    return open_price * (Decimal("1") + config.slippage_bps / Decimal("10000"))


def buy_fee(quantity: int, price: Decimal, config: ExecutionConfig) -> Decimal:
    if quantity <= 0:
        return Decimal("0")
    fee = Decimal(quantity) * price * config.fee_rate
    return max(fee, config.min_fee)


def shares_for_target(
    cash: Decimal,
    target_weight: float,
    price: Decimal,
    lot_size: int = 100,
    fee_rate: Decimal = Decimal("0"),
    min_fee: Decimal = Decimal("0"),
) -> int:
    budget = cash * Decimal(str(target_weight))
    raw = int(budget / price)
    quantity = (raw // lot_size) * lot_size
    config = ExecutionConfig(fee_rate=fee_rate, min_fee=min_fee, lot_size=lot_size)
    while quantity > 0 and Decimal(quantity) * price + buy_fee(quantity, price, config) > budget:
        quantity -= lot_size
    return quantity
