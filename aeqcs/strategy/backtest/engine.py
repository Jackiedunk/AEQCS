"""Minimal deterministic daily backtest engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from aeqcs.strategy.backtest.execution import (
    ExecutionConfig,
    Fill,
    buy_fee,
    buy_price_with_slippage,
    sell_fee,
    sell_price_with_slippage,
    shares_for_target,
)
from aeqcs.strategy.base import Signal, Strategy
from aeqcs.strategy.portfolio import Portfolio
from aeqcs.strategy.tradability import TradabilityInput, can_buy, can_sell


@dataclass(frozen=True, slots=True)
class BacktestResult:
    fills: list[Fill]
    nav: list[tuple[date, Decimal]]
    orders: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class BacktestReport:
    backtest_result_id: str
    strategy_name: str
    start_date: date
    end_date: date
    as_of_date: date
    parameters: dict
    fills: list[Fill]
    nav: list[tuple[date, Decimal]]
    orders: list[dict[str, Any]]


def _bars_by_symbol(rows: list[dict]) -> dict[str, list[dict]]:
    ordered = sorted(rows, key=lambda row: (row["symbol"], row["date"]))
    mapping: dict[str, list[dict]] = {}
    for row in ordered:
        mapping.setdefault(row["symbol"], []).append(row)
    return mapping


def run_daily_backtest(
    market_panel: Iterable[dict],
    strategy: Strategy,
    initial_cash: Decimal = Decimal("1000000"),
    execution: ExecutionConfig | None = None,
) -> BacktestResult:
    execution = execution or ExecutionConfig()
    rows = sorted(list(market_panel), key=lambda row: (row["date"], row["symbol"]))
    signals = strategy.generate_signals(rows)
    signals_by_date: dict[date, list[tuple[int, Signal]]] = {}
    for index, signal in enumerate(signals):
        signals_by_date.setdefault(signal.date, []).append((index, signal))

    bars_by_symbol = _bars_by_symbol(rows)
    portfolio = Portfolio(initial_cash)
    fills: list[Fill] = []
    orders: list[dict[str, Any]] = []
    pending_fills: dict[date, list[Fill]] = {}
    nav: list[tuple[date, Decimal]] = []

    dates = sorted({row["date"] for row in rows})
    for current_date in dates:
        for fill in pending_fills.pop(current_date, []):
            portfolio.apply_fill(fill.symbol, fill.quantity, fill.price, fill.fee)
            fills.append(fill)

        for order_index, signal in signals_by_date.get(current_date, []):
            current_position = portfolio.positions.get(signal.symbol, 0)
            if signal.target_weight <= 0 and current_position > 0:
                execution_bar = _first_executable_bar(
                    bars_by_symbol,
                    signal.symbol,
                    current_date,
                    _can_sell_bar,
                )
                if not execution_bar:
                    orders.append(_order_record(order_index, signal, "sell", "expired", reason="no_executable_bar"))
                    continue
                price = sell_price_with_slippage(Decimal(str(execution_bar["open"])), execution)
                desired_quantity = current_position
                quantity = -min(desired_quantity, _volume_cap(execution_bar, execution.lot_size))
                fill = Fill(
                    execution_bar["date"],
                    signal.symbol,
                    quantity,
                    price,
                    sell_fee(quantity, price, execution),
                )
                pending_fills.setdefault(fill.date, []).append(fill)
                status, reason = _fill_status(abs(quantity), desired_quantity)
                orders.append(_order_record(order_index, signal, "sell", status, fill=fill, reason=reason))
                continue
            if signal.target_weight <= 0:
                orders.append(_order_record(order_index, signal, "sell", "rejected", reason="no_position"))
                continue
            execution_bar = _first_executable_bar(
                bars_by_symbol,
                signal.symbol,
                current_date,
                _can_buy_bar,
            )
            if not execution_bar:
                orders.append(_order_record(order_index, signal, "buy", "expired", reason="no_executable_bar"))
                continue
            if not _can_buy_bar(execution_bar):
                orders.append(_order_record(order_index, signal, "buy", "expired", reason="not_tradable"))
                continue
            price = buy_price_with_slippage(Decimal(str(execution_bar["open"])), execution)
            desired_quantity = shares_for_target(
                portfolio.cash,
                signal.target_weight,
                price,
                lot_size=execution.lot_size,
                fee_rate=execution.fee_rate,
                min_fee=execution.min_fee,
            )
            quantity = min(desired_quantity, _volume_cap(execution_bar, execution.lot_size))
            if quantity > 0:
                fill = Fill(
                    execution_bar["date"],
                    signal.symbol,
                    quantity,
                    price,
                    buy_fee(quantity, price, execution),
                )
                pending_fills.setdefault(fill.date, []).append(fill)
                status, reason = _fill_status(quantity, desired_quantity)
                orders.append(_order_record(order_index, signal, "buy", status, fill=fill, reason=reason))
            else:
                orders.append(_order_record(order_index, signal, "buy", "expired", reason="zero_quantity"))

        close_prices = {row["symbol"]: _mark_price(row) for row in rows if row["date"] == current_date}
        nav.append((current_date, portfolio.market_value(close_prices)))

    return BacktestResult(fills=fills, nav=nav, orders=orders)


def _fill_status(filled_quantity: int, desired_quantity: int) -> tuple[str, str]:
    if filled_quantity < desired_quantity:
        return "partial_filled", "volume_limited"
    return "filled", "filled"


def _order_record(
    order_index: int,
    signal: Signal,
    side: str,
    status: str,
    *,
    fill: Fill | None = None,
    reason: str = "filled",
) -> dict[str, Any]:
    return {
        "order_id": f"{signal.date.isoformat()}:{signal.symbol}:{side}:{order_index}",
        "submitted_date": signal.date,
        "symbol": signal.symbol,
        "side": side,
        "target_weight": signal.target_weight,
        "status": status,
        "execution_date": fill.date if fill else None,
        "quantity": abs(fill.quantity) if fill else 0,
        "reason": reason,
    }


def _first_executable_bar(
    bars_by_symbol: dict[str, list[dict]],
    symbol: str,
    signal_date: date,
    predicate,
) -> dict | None:
    for row in bars_by_symbol.get(symbol, []):
        if row["date"] <= signal_date:
            continue
        if predicate(row):
            return row
    return None


def _can_buy_bar(row: dict) -> bool:
    return can_buy(
        TradabilityInput(
            is_trading=bool(row.get("is_trading", True)),
            is_suspend=bool(row.get("is_suspend", False)),
            is_one_word_limit=bool(row.get("is_one_word_limit", False)),
            bid_volume=int(row.get("bid_volume", 1)),
            ask_volume=_ask_volume(row),
        )
    )


def _can_sell_bar(row: dict) -> bool:
    return can_sell(
        TradabilityInput(
            is_trading=bool(row.get("is_trading", True)),
            is_suspend=bool(row.get("is_suspend", False)),
            is_one_word_limit=bool(row.get("is_one_word_limit", False)),
            bid_volume=_bid_volume(row),
            ask_volume=int(row.get("ask_volume", 1)),
        )
    )


def _volume_cap(row: dict, lot_size: int) -> int:
    if "volume" not in row:
        return 10**18
    volume = max(int(row.get("volume") or 0), 0)
    return (volume // lot_size) * lot_size


def _ask_volume(row: dict) -> int:
    if "ask_volume" in row:
        return int(row.get("ask_volume") or 0)
    if _at_limit(row, "high_limit"):
        return 0
    return 1


def _bid_volume(row: dict) -> int:
    if "bid_volume" in row:
        return int(row.get("bid_volume") or 0)
    if _at_limit(row, "low_limit"):
        return 0
    return 1


def _at_limit(row: dict, field: str) -> bool:
    if field not in row:
        return False
    return Decimal(str(row["open"])) == Decimal(str(row[field]))


def _mark_price(row: dict) -> Decimal:
    if bool(row.get("is_one_word_limit", False)) and "low_limit" in row:
        return Decimal(str(row["low_limit"]))
    return Decimal(str(row["close"]))
