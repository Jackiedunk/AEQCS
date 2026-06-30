"""AEQCS-to-Qlib data adapter boundary.

Qlib is optional at install time. This module keeps all imports lazy so the
deterministic core can run without Qlib during bootstrap and tests.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from aeqcs.core.versioning import require_as_of


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
        require_as_of(as_of_date)
        query = """
        SELECT date, symbol AS instrument, open, high, low, close, volume, amount
        FROM stock_daily_origin
        WHERE symbol = ANY($1) AND date BETWEEN $2 AND $3 AND date <= $4
        ORDER BY date, symbol
        """
        async with self.pg_pool.acquire() as conn:
            rows = await conn.fetch(query, symbols, start_date, end_date, as_of_date)
        df = pd.DataFrame([dict(r) for r in rows])
        if df.empty:
            return pd.DataFrame()
        return df.set_index(["date", "instrument"]).sort_index()

    async def get_pit_financials(
        self,
        symbols: list[str],
        period: str,
        as_of_date: date | None = None,
    ) -> pd.DataFrame:
        require_as_of(as_of_date)
        query = """
        SELECT DISTINCT ON (symbol, period)
          symbol AS instrument, period, ann_date, vintage, roe, eps, bps,
          revenue_yoy, profit_yoy, debt_ratio, current_ratio
        FROM financial_indicators
        WHERE symbol = ANY($1) AND period = $2 AND ann_date <= $3
        ORDER BY symbol, period, ann_date DESC, vintage DESC
        """
        async with self.pg_pool.acquire() as conn:
            rows = await conn.fetch(query, symbols, period, as_of_date)
        return pd.DataFrame([dict(r) for r in rows])


async def inject_aeqcs_data(
    handler: Any,
    provider: AeQCSDataProvider,
    symbols: list[str],
    start_date: date,
    end_date: date,
    as_of_date: date,
) -> Any:
    handler._data = await provider.get_market_data(symbols, start_date, end_date, as_of_date)
    return handler
