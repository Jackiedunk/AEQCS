"""Run a tiny deterministic backtest against built-in sample rows."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from decimal import Decimal

from aeqcs.strategy.backtest.engine import run_daily_backtest
from aeqcs.strategy.base import BuyAndHoldStrategy


def main() -> None:
    panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {"symbol": "000001", "date": date(2026, 1, 2), "open": "11", "close": "12"},
        {"symbol": "000001", "date": date(2026, 1, 5), "open": "12", "close": "11.8"},
    ]
    result = run_daily_backtest(panel, BuyAndHoldStrategy("000001"), Decimal("1000000"))
    print({"fills": [asdict(fill) for fill in result.fills], "nav": result.nav})


if __name__ == "__main__":
    main()
