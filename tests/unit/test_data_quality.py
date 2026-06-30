from datetime import date
from decimal import Decimal

from aeqcs.data.models import DailyBar
from aeqcs.data.quality.validator import validate_daily_bar


def test_validate_daily_bar_rejects_bad_ohlc():
    bar = DailyBar(
        symbol="000001",
        date=date(2026, 1, 1),
        open=Decimal("10"),
        high=Decimal("9"),
        low=Decimal("8"),
        close=Decimal("10"),
        volume=1,
        amount=Decimal("10"),
    )

    assert validate_daily_bar(bar)
