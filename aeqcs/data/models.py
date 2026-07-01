"""Canonical data records used across ETL, factors, and backtests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class DailyBar:
    symbol: str
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: Decimal

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> "DailyBar":
        return cls(
            symbol=str(row["symbol"]),
            date=date.fromisoformat(str(row["date"])),
            open=Decimal(str(row["open"])),
            high=Decimal(str(row["high"])),
            low=Decimal(str(row["low"])),
            close=Decimal(str(row["close"])),
            volume=int(row["volume"]),
            amount=Decimal(str(row["amount"])),
        )


@dataclass(frozen=True, slots=True)
class FinancialIndicator:
    symbol: str
    period: str
    ann_date: date
    vintage: int
    values: dict[str, Decimal]

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> "FinancialIndicator":
        keys = (
            "roe",
            "eps",
            "bps",
            "revenue_yoy",
            "profit_yoy",
            "debt_ratio",
            "current_ratio",
            "quick_ratio",
            "gross_margin",
            "net_margin",
        )
        values = {key: Decimal(str(row[key])) for key in keys if row.get(key) is not None}
        return cls(
            symbol=str(row["symbol"]),
            period=str(row["period"]),
            ann_date=date.fromisoformat(str(row["ann_date"])),
            vintage=int(row.get("vintage", 0)),
            values=values,
        )


@dataclass(frozen=True, slots=True)
class FactorValue:
    symbol: str
    date: date
    factor_id: str
    version: int
    value: Decimal
    calc_timestamp: datetime
