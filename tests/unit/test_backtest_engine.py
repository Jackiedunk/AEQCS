from datetime import date
from decimal import Decimal

from aeqcs.strategy.backtest.execution import ExecutionConfig
from aeqcs.strategy.backtest.engine import run_daily_backtest
from aeqcs.strategy.base import BuyAndHoldStrategy, Signal


class TwoSignalStrategy:
    strategy_id = "two_signal"

    def generate_signals(self, market_panel):
        return [
            Signal(date(2026, 1, 1), "000001", 1.0, "buy"),
            Signal(date(2026, 1, 2), "000001", 0.0, "sell"),
        ]


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


def test_backtest_delays_fill_when_next_day_bar_is_suspended():
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

    assert len(result.fills) == 1
    assert result.fills[0].date == date(2026, 1, 3)
    assert result.fills[0].price == Decimal("10")


def test_backtest_skips_one_word_limit_and_no_ask_volume():
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
    no_ask_panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {
            "symbol": "000001",
            "date": date(2026, 1, 2),
            "open": "10",
            "close": "10",
            "ask_volume": 0,
        },
    ]

    assert run_daily_backtest(one_word_limit_panel, BuyAndHoldStrategy("000001")).fills == []
    assert run_daily_backtest(no_ask_panel, BuyAndHoldStrategy("000001")).fills == []


def test_backtest_blocks_buy_at_limit_up_without_ask_volume():
    panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {
            "symbol": "000001",
            "date": date(2026, 1, 2),
            "open": "11",
            "close": "11",
            "high_limit": "11",
        },
    ]

    assert run_daily_backtest(panel, BuyAndHoldStrategy("000001"), Decimal("10000")).fills == []


def test_backtest_sells_on_next_open_when_target_weight_goes_to_zero():
    panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {"symbol": "000001", "date": date(2026, 1, 2), "open": "10", "close": "10"},
        {"symbol": "000001", "date": date(2026, 1, 3), "open": "9", "close": "9"},
    ]

    result = run_daily_backtest(panel, TwoSignalStrategy(), Decimal("10000"))

    assert [fill.quantity for fill in result.fills] == [1000, -1000]
    assert result.fills[1].date == date(2026, 1, 3)
    assert result.fills[1].price == Decimal("9")


def test_backtest_blocks_sell_on_one_word_limit_down_or_no_bid_volume():
    one_word_limit_down_panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {"symbol": "000001", "date": date(2026, 1, 2), "open": "10", "close": "10"},
        {
            "symbol": "000001",
            "date": date(2026, 1, 3),
            "open": "9",
            "close": "9",
            "is_one_word_limit": True,
            "low_limit": "9",
            "ask_volume": 1000,
        },
    ]
    no_bid_panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {"symbol": "000001", "date": date(2026, 1, 2), "open": "10", "close": "10"},
        {
            "symbol": "000001",
            "date": date(2026, 1, 3),
            "open": "9",
            "close": "9",
            "bid_volume": 0,
        },
    ]

    assert [fill.quantity for fill in run_daily_backtest(one_word_limit_down_panel, TwoSignalStrategy(), Decimal("10000")).fills] == [1000]
    assert [fill.quantity for fill in run_daily_backtest(no_bid_panel, TwoSignalStrategy(), Decimal("10000")).fills] == [1000]


def test_backtest_blocks_sell_at_limit_down_without_bid_volume():
    panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {"symbol": "000001", "date": date(2026, 1, 2), "open": "10", "close": "10"},
        {
            "symbol": "000001",
            "date": date(2026, 1, 3),
            "open": "9",
            "close": "9",
            "low_limit": "9",
        },
    ]

    assert [fill.quantity for fill in run_daily_backtest(panel, TwoSignalStrategy(), Decimal("10000")).fills] == [1000]


def test_backtest_marks_one_word_limit_down_position_at_low_limit_price():
    panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {"symbol": "000001", "date": date(2026, 1, 2), "open": "10", "close": "10"},
        {
            "symbol": "000001",
            "date": date(2026, 1, 3),
            "open": "9",
            "close": "10",
            "low_limit": "9",
            "is_one_word_limit": True,
        },
        {
            "symbol": "000001",
            "date": date(2026, 1, 4),
            "open": "8.1",
            "close": "10",
            "low_limit": "8.1",
            "is_one_word_limit": True,
        },
    ]

    result = run_daily_backtest(panel, TwoSignalStrategy(), Decimal("10000"))

    assert [fill.quantity for fill in result.fills] == [1000]
    assert result.nav[-2:] == [
        (date(2026, 1, 3), Decimal("9000")),
        (date(2026, 1, 4), Decimal("8100.0")),
    ]


def test_backtest_caps_buy_quantity_by_bar_volume():
    panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {"symbol": "000001", "date": date(2026, 1, 2), "open": "10", "close": "10", "volume": 300},
    ]

    result = run_daily_backtest(panel, BuyAndHoldStrategy("000001"), Decimal("10000"))

    assert [fill.quantity for fill in result.fills] == [300]
    assert result.orders[0]["status"] == "partial_filled"
    assert result.orders[0]["quantity"] == 300
    assert result.orders[0]["reason"] == "volume_limited"


def test_backtest_caps_sell_quantity_by_bar_volume():
    panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {"symbol": "000001", "date": date(2026, 1, 2), "open": "10", "close": "10"},
        {"symbol": "000001", "date": date(2026, 1, 3), "open": "9", "close": "9", "volume": 400},
    ]

    result = run_daily_backtest(panel, TwoSignalStrategy(), Decimal("10000"))

    assert [fill.quantity for fill in result.fills] == [1000, -400]
    assert result.orders[1]["status"] == "partial_filled"
    assert result.orders[1]["quantity"] == 400
    assert result.orders[1]["reason"] == "volume_limited"


def test_backtest_records_filled_and_expired_order_lifecycle():
    panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {"symbol": "000001", "date": date(2026, 1, 2), "open": "10", "close": "10"},
        {"symbol": "000002", "date": date(2026, 1, 1), "open": "20", "close": "20"},
        {
            "symbol": "000002",
            "date": date(2026, 1, 2),
            "open": "20",
            "close": "20",
            "is_suspend": True,
        },
    ]

    class MixedLifecycleStrategy:
        strategy_id = "mixed_lifecycle"

        def generate_signals(self, market_panel):
            return [
                Signal(date(2026, 1, 1), "000001", 0.5, "buy"),
                Signal(date(2026, 1, 1), "000002", 0.5, "buy"),
            ]

    result = run_daily_backtest(panel, MixedLifecycleStrategy(), Decimal("10000"))

    assert [order["status"] for order in result.orders] == ["filled", "expired"]
    assert result.orders[0] == {
        "order_id": "2026-01-01:000001:buy:0",
        "submitted_date": date(2026, 1, 1),
        "symbol": "000001",
        "side": "buy",
        "target_weight": 0.5,
        "status": "filled",
        "execution_date": date(2026, 1, 2),
        "quantity": 500,
        "reason": "filled",
    }
    assert result.orders[1] == {
        "order_id": "2026-01-01:000002:buy:1",
        "submitted_date": date(2026, 1, 1),
        "symbol": "000002",
        "side": "buy",
        "target_weight": 0.5,
        "status": "expired",
        "execution_date": None,
        "quantity": 0,
        "reason": "no_executable_bar",
    }


def test_backtest_rejects_sell_order_without_position():
    panel = [
        {"symbol": "000001", "date": date(2026, 1, 1), "open": "10", "close": "10"},
        {"symbol": "000001", "date": date(2026, 1, 2), "open": "10", "close": "10"},
    ]

    class SellWithoutPositionStrategy:
        strategy_id = "sell_without_position"

        def generate_signals(self, market_panel):
            return [Signal(date(2026, 1, 1), "000001", 0.0, "sell")]

    result = run_daily_backtest(panel, SellWithoutPositionStrategy(), Decimal("10000"))

    assert result.fills == []
    assert result.orders == [
        {
            "order_id": "2026-01-01:000001:sell:0",
            "submitted_date": date(2026, 1, 1),
            "symbol": "000001",
            "side": "sell",
            "target_weight": 0.0,
            "status": "rejected",
            "execution_date": None,
            "quantity": 0,
            "reason": "no_position",
        }
    ]
