"""Strategy interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Signal:
    date: date
    symbol: str
    target_weight: float
    reason: str = ""


class Strategy(Protocol):
    strategy_id: str

    def generate_signals(self, market_panel) -> list[Signal]:
        ...


class BuyAndHoldStrategy:
    strategy_id = "buy_and_hold"

    def __init__(self, symbol: str, target_weight: float = 1.0) -> None:
        self.symbol = symbol
        self.target_weight = target_weight

    def generate_signals(self, market_panel) -> list[Signal]:
        first_date = min(row["date"] for row in market_panel if row["symbol"] == self.symbol)
        return [Signal(first_date, self.symbol, self.target_weight, "initial buy")]
