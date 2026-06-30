"""Simple long-only portfolio accounting."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(slots=True)
class Portfolio:
    cash: Decimal
    positions: dict[str, int] = field(default_factory=dict)

    def market_value(self, prices: dict[str, Decimal]) -> Decimal:
        value = self.cash
        for symbol, quantity in self.positions.items():
            value += prices.get(symbol, Decimal("0")) * quantity
        return value

    def apply_fill(self, symbol: str, quantity: int, price: Decimal, fee: Decimal = Decimal("0")) -> None:
        self.cash -= Decimal(quantity) * price + fee
        self.positions[symbol] = self.positions.get(symbol, 0) + quantity
