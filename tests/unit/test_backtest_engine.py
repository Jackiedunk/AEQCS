from datetime import date
from decimal import Decimal

from aeqcs.strategy.backtest.execution import ExecutionConfig
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


def test_backtest_applies_slippage_and_fee_without_overspending():
    panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {"symbol": "000001", "date": date(2026, 1, 2), "open": "10", "close": "10"},
    ]

    result = run_daily_backtest(
        panel,
        BuyAndHoldStrategy("000001"),
        Decimal("10000"),
        ExecutionConfig(
            fee_rate=Decimal("0.001"),
            min_fee=Decimal("5"),
            slippage_bps=Decimal("10"),
        ),
    )

    assert result.fills[0].price == Decimal("10.010")
    assert result.fills[0].quantity == 900
    assert result.fills[0].fee == Decimal("9.009000")
    assert result.nav[-1][1] == Decimal("9981.991000")


def test_backtest_skips_untradable_next_day_bar():
    panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {
            "symbol": "000001",
            "date": date(2026, 1, 2),
            "open": "10",
            "close": "10",
            "is_suspend": True,
            "bid_volume": 1000,
        },
        {"symbol": "000001", "date": date(2026, 1, 3), "open": "10", "close": "10"},
    ]

    result = run_daily_backtest(panel, BuyAndHoldStrategy("000001"), Decimal("10000"))

    assert result.fills == []


def test_backtest_skips_one_word_limit_and_no_bid_volume():
    one_word_limit_panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {
            "symbol": "000001",
            "date": date(2026, 1, 2),
            "open": "10",
            "close": "10",
            "is_one_word_limit": True,
            "bid_volume": 1000,
        },
    ]
    no_bid_panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {
            "symbol": "000001",
            "date": date(2026, 1, 2),
            "open": "10",
            "close": "10",
            "bid_volume": 0,
        },
    ]

    assert run_daily_backtest(one_word_limit_panel, BuyAndHoldStrategy("000001")).fills == []
    assert run_daily_backtest(no_bid_panel, BuyAndHoldStrategy("000001")).fills == []
