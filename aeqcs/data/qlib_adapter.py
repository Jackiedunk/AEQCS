"""AEQCS-to-Qlib data adapter boundary.

Qlib is optional at install time. This module keeps all imports lazy so the
deterministic core can run without Qlib during bootstrap and tests.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, cast

import pandas as pd
import duckdb

from aeqcs.core.versioning import (
    assert_not_after,
    require_as_of,
    require_date_value,
    require_finite_number,
    require_non_empty_text,
)


DEFAULT_QLIB_MAX_PANDAS_ROWS = 250_000
DEFAULT_QLIB_MAX_SYMBOLS = 800
QLIB_MARKET_ID_COLUMNS = {"date", "instrument"}
QLIB_FINANCIAL_ID_COLUMNS = {"instrument", "period", "ann_date", "vintage"}


class QlibBoundaryError(ValueError):
    """Raised when data would violate AEQCS Qlib boundary constraints."""


def _date_values(frame: pd.DataFrame) -> pd.Series:
    if isinstance(frame.index, pd.MultiIndex) and "date" in frame.index.names:
        return pd.Series(frame.index.get_level_values("date"))
    if frame.index.name == "date":
        return pd.Series(frame.index)
    if "date" in frame.columns:
        return frame["date"]
    return pd.Series([], dtype="object")


def _instrument_values(frame: pd.DataFrame) -> pd.Series:
    if isinstance(frame.index, pd.MultiIndex) and "instrument" in frame.index.names:
        return pd.Series(frame.index.get_level_values("instrument"))
    if frame.index.name == "instrument":
        return pd.Series(frame.index)
    if "instrument" in frame.columns:
        return frame["instrument"]
    return pd.Series([], dtype="object")


def ensure_qlib_market_frame_safe(
    frame: pd.DataFrame,
    as_of_date: date | None,
    *,
    max_rows: int = DEFAULT_QLIB_MAX_PANDAS_ROWS,
    max_symbols: int = DEFAULT_QLIB_MAX_SYMBOLS,
) -> pd.DataFrame:
    checked_as_of = require_as_of(as_of_date)
    if len(frame) > max_rows:
        raise QlibBoundaryError(
            f"market panel has {len(frame)} rows and exceeds Qlib pandas row budget {max_rows}"
        )

    instruments = _instrument_values(frame)
    if instruments.empty:
        raise QlibBoundaryError("market panel requires instrument")
    if not instruments.empty:
        instruments = instruments.map(lambda value: _qlib_required_text(value, "instrument"))
    if not instruments.empty and instruments.nunique() > max_symbols:
        raise QlibBoundaryError(
            f"market panel has {instruments.nunique()} instruments and exceeds budget {max_symbols}"
        )

    dates = _date_values(frame)
    if dates.empty:
        raise QlibBoundaryError("market panel requires date")
    if not dates.empty:
        dates = dates.map(lambda value: _qlib_required_date(value, "date"))
        latest_date = cast(date, dates.max())
        assert_not_after(latest_date, checked_as_of)
    axis_frame = pd.DataFrame(
        {"date": dates.to_list(), "instrument": instruments.to_list()}
    )
    if axis_frame.duplicated().any():
        raise QlibBoundaryError("market panel has duplicate date/instrument rows")

    for column in frame.columns:
        if column not in QLIB_MARKET_ID_COLUMNS:
            frame[column].map(lambda value, field=column: _qlib_finite_number(value, field))

    return frame.copy()


def build_pit_financial_snapshot(
    frame: pd.DataFrame,
    as_of_date: date | None,
) -> pd.DataFrame:
    checked_as_of = require_as_of(as_of_date)
    if frame.empty:
        return frame.copy()
    required = {"instrument", "period", "ann_date", "vintage"}
    missing = required - set(frame.columns)
    if missing:
        raise QlibBoundaryError(f"financial snapshot missing columns: {sorted(missing)}")

    snapshot = frame.copy()
    snapshot["instrument"] = snapshot["instrument"].map(
        lambda value: _qlib_required_text(value, "instrument")
    )
    snapshot["period"] = snapshot["period"].map(lambda value: _qlib_required_text(value, "period"))
    snapshot["ann_date"] = snapshot["ann_date"].map(lambda value: _qlib_required_date(value, "ann_date"))
    snapshot["vintage"] = snapshot["vintage"].map(
        lambda value: _qlib_non_negative_integer(value, "vintage")
    )
    if snapshot.duplicated(subset=["instrument", "period", "ann_date", "vintage"]).any():
        raise QlibBoundaryError("financial snapshot has duplicate financial version rows")
    for column in snapshot.columns:
        if column not in QLIB_FINANCIAL_ID_COLUMNS:
            snapshot[column] = snapshot[column].map(
                lambda value, field=column: _qlib_optional_finite_number(value, field)
            )
    snapshot = snapshot[snapshot["ann_date"] <= checked_as_of]
    if snapshot.empty:
        return snapshot.reset_index(drop=True)

    for ann_date in snapshot["ann_date"]:
        assert_not_after(ann_date, checked_as_of)
    result = (
        duckdb.sql(
            """
            SELECT DISTINCT ON (instrument, period) *
            FROM snapshot
            ORDER BY instrument, period, ann_date DESC, vintage DESC
            """
        )
        .df()
        .sort_values(["instrument", "period"])
        .reset_index(drop=True)
    )
    result["ann_date"] = pd.to_datetime(result["ann_date"]).dt.date
    return result


def _qlib_required_text(value: Any, field: str) -> str:
    try:
        return require_non_empty_text(value, field)
    except ValueError as exc:
        raise QlibBoundaryError(str(exc)) from exc


def _qlib_required_date(value: Any, field: str) -> date:
    try:
        return require_date_value(value, field)
    except ValueError as exc:
        raise QlibBoundaryError(str(exc)) from exc


def _qlib_non_negative_integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise QlibBoundaryError(f"{field} must be a non-negative integer")
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise QlibBoundaryError(f"{field} must be a non-negative integer") from exc
    if not math.isfinite(numeric) or numeric < 0 or not numeric.is_integer():
        raise QlibBoundaryError(f"{field} must be a non-negative integer")
    return int(numeric)


def _qlib_optional_finite_number(value: Any, field: str) -> Any:
    if value is None:
        return value
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, bool) and missing:
        return value
    try:
        return require_finite_number(value, field)
    except ValueError as exc:
        raise QlibBoundaryError(str(exc)) from exc


def _qlib_finite_number(value: Any, field: str) -> Any:
    try:
        return require_finite_number(value, field)
    except ValueError as exc:
        raise QlibBoundaryError(str(exc)) from exc


class AeQCSDataProvider:
    def __init__(self, pg_pool: Any) -> None:
        self.pg_pool = pg_pool

    async def get_market_data(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        as_of_date: date | None = None,
    ) -> pd.DataFrame:
        checked_as_of = require_as_of(as_of_date)
        query = """
        SELECT date, symbol AS instrument, open, high, low, close, volume, amount
        FROM stock_daily_origin
        WHERE symbol = ANY($1) AND date BETWEEN $2 AND $3 AND date <= $4
        ORDER BY date, symbol
        """
        async with self.pg_pool.acquire() as conn:
            rows = await conn.fetch(query, symbols, start_date, end_date, checked_as_of)
        df = pd.DataFrame([dict(r) for r in rows])
        if df.empty:
            return pd.DataFrame()
        indexed = df.set_index(["date", "instrument"]).sort_index()
        return ensure_qlib_market_frame_safe(indexed, checked_as_of)

    async def get_pit_financials(
        self,
        symbols: list[str],
        period: str,
        as_of_date: date | None = None,
    ) -> pd.DataFrame:
        checked_as_of = require_as_of(as_of_date)
        query = """
        SELECT DISTINCT ON (symbol, period)
          symbol AS instrument, period, ann_date, vintage, roe, eps, bps,
          revenue_yoy, profit_yoy, debt_ratio, current_ratio, quick_ratio, gross_margin, net_margin
        FROM financial_indicators
        WHERE symbol = ANY($1) AND period = $2 AND ann_date <= $3
        ORDER BY symbol, period, ann_date DESC, vintage DESC
        """
        async with self.pg_pool.acquire() as conn:
            rows = await conn.fetch(query, symbols, period, checked_as_of)
        return build_pit_financial_snapshot(pd.DataFrame([dict(r) for r in rows]), checked_as_of)


async def inject_aeqcs_data(
    handler: Any,
    provider: AeQCSDataProvider,
    symbols: list[str],
    start_date: date,
    end_date: date,
    as_of_date: date,
) -> Any:
    data = await provider.get_market_data(symbols, start_date, end_date, as_of_date)
    handler._data = ensure_qlib_market_frame_safe(data, as_of_date)
    return handler
