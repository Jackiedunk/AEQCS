from datetime import date
from decimal import Decimal

from aeqcs.strategy.backtest.engine import run_daily_backtest
from aeqcs.strategy.base import BuyAndHoldStrategy


def test_backtest_uses_next_day_open_for_fill():
    panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {"symbol": "000001", "date": date(2026, 1, 2), "open": "11", "close": "12"},
    ]

    result = run_daily_backtest(panel, BuyAndHoldStrategy("000001"), Decimal("10000"))

    assert result.fills[0].date == date(2026, 1, 2)
    assert result.fills[0].price == Decimal("11")
    assert result.nav[0] == (date(2026, 1, 1), Decimal("10000"))
