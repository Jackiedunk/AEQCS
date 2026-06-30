"""Data quality checks for canonical market data."""

from __future__ import annotations

from aeqcs.data.models import DailyBar, FinancialIndicator


def validate_daily_bar(bar: DailyBar) -> list[str]:
    errors: list[str] = []
    if bar.high < max(bar.open, bar.close, bar.low):
        errors.append("high is below one or more OHLC values")
    if bar.low > min(bar.open, bar.close, bar.high):
        errors.append("low is above one or more OHLC values")
    if bar.volume < 0:
        errors.append("volume is negative")
    if bar.amount < 0:
        errors.append("amount is negative")
    return errors


def validate_financial_indicator(record: FinancialIndicator) -> list[str]:
    errors: list[str] = []
    if not record.symbol:
        errors.append("symbol is required")
    if not record.period:
        errors.append("period is required")
    return errors
