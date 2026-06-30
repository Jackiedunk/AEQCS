"""Minimal deterministic daily backtest engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from aeqcs.strategy.backtest.execution import Fill, shares_for_target
from aeqcs.strategy.base import Signal, Strategy
from aeqcs.strategy.portfolio import Portfolio


@dataclass(frozen=True, slots=True)
class BacktestResult:
    fills: list[Fill]
    nav: list[tuple[date, Decimal]]


def _next_bar_by_symbol(rows: list[dict]) -> dict[tuple[str, date], dict]:
    ordered = sorted(rows, key=lambda row: (row["symbol"], row["date"]))
    mapping: dict[tuple[str, date], dict] = {}
    for index, row in enumerate(ordered[:-1]):
        nxt = ordered[index + 1]
        if nxt["symbol"] == row["symbol"]:
            mapping[(row["symbol"], row["date"])] = nxt
    return mapping


def run_daily_backtest(
    market_panel: Iterable[dict],
    strategy: Strategy,
    initial_cash: Decimal = Decimal("1000000"),
) -> BacktestResult:
    rows = sorted(list(market_panel), key=lambda row: (row["date"], row["symbol"]))
    signals = strategy.generate_signals(rows)
    signals_by_date: dict[date, list[Signal]] = {}
    for signal in signals:
        signals_by_date.setdefault(signal.date, []).append(signal)

    next_bar = _next_bar_by_symbol(rows)
    portfolio = Portfolio(initial_cash)
    fills: list[Fill] = []
    pending_fills: dict[date, list[Fill]] = {}
    nav: list[tuple[date, Decimal]] = []

    dates = sorted({row["date"] for row in rows})
    for current_date in dates:
        for fill in pending_fills.pop(current_date, []):
            portfolio.apply_fill(fill.symbol, fill.quantity, fill.price, fill.fee)
            fills.append(fill)

        for signal in signals_by_date.get(current_date, []):
            execution_bar = next_bar.get((signal.symbol, current_date))
            if not execution_bar:
                continue
            price = Decimal(str(execution_bar["open"]))
            quantity = shares_for_target(portfolio.cash, signal.target_weight, price)
            if quantity > 0:
                fill = Fill(execution_bar["date"], signal.symbol, quantity, price)
                pending_fills.setdefault(fill.date, []).append(fill)

        close_prices = {
            row["symbol"]: Decimal(str(row["close"])) for row in rows if row["date"] == current_date
        }
        nav.append((current_date, portfolio.market_value(close_prices)))

    return BacktestResult(fills=fills, nav=nav)
