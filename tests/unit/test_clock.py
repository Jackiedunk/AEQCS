from datetime import date

from aeqcs.core.clock import is_trading_day, next_trading_day, prev_trading_day


def test_weekend_is_not_trading_day():
    assert not is_trading_day(date(2026, 6, 27))


def test_prev_next_skip_weekend():
    assert prev_trading_day(date(2026, 6, 29)) == date(2026, 6, 26)
    assert next_trading_day(date(2026, 6, 26)) == date(2026, 6, 29)
