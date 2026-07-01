"""Tushare adapter with lazy imports and normalized outputs."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

import pandas as pd

from aeqcs.core.exceptions import ConfigurationError, DataSourceError
from aeqcs.core.versioning import require_non_empty_text
from aeqcs.data.etl.financial_data import normalize_financial_frame
from aeqcs.data.etl.market_data import normalize_daily_frame
from aeqcs.data.rate_limiter import RateLimiter


class TushareClient(Protocol):
    def daily(self, **kwargs: Any) -> pd.DataFrame:
        ...

    def fina_indicator(self, **kwargs: Any) -> pd.DataFrame:
        ...


def _fmt_day(day: date) -> str:
    return day.strftime("%Y%m%d")


def _valid_symbol(symbol: str) -> str:
    return require_non_empty_text(symbol, "symbol")


def _assert_date_range(start: date, end: date) -> None:
    if start > end:
        raise ValueError("start must be on or before end")


def _normalize_provider_frame(frame: pd.DataFrame, source: str, normalize_fn: Any) -> pd.DataFrame:
    try:
        return normalize_fn(frame)
    except ValueError as exc:
        raise DataSourceError(f"{source} invalid row: {exc}") from exc


class TushareAdapter:
    def __init__(
        self,
        token: str | None = None,
        client: TushareClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.token = token
        self._client = client
        self.rate_limiter = rate_limiter

    @property
    def client(self) -> TushareClient:
        if self._client is not None:
            return self._client
        if not self.token:
            raise ConfigurationError("TUSHARE_TOKEN is required when no client is injected")
        try:
            import tushare as ts  # type: ignore
        except ImportError as exc:
            raise ConfigurationError("install the data extra to use Tushare") from exc
        ts.set_token(self.token)
        self._client = ts.pro_api()
        return self._client

    def daily(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        checked_symbol = _valid_symbol(symbol)
        _assert_date_range(start, end)
        if self.rate_limiter:
            self.rate_limiter.consume("tushare")
        raw = self.client.daily(ts_code=checked_symbol, start_date=_fmt_day(start), end_date=_fmt_day(end))
        if raw is None or raw.empty:
            return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"])
        rename = {"ts_code": "symbol", "trade_date": "date", "vol": "volume"}
        frame = raw.rename(columns=rename)
        missing = {"symbol", "date", "open", "high", "low", "close", "volume", "amount"} - set(frame.columns)
        if missing:
            raise DataSourceError(f"Tushare daily missing columns: {sorted(missing)}")
        return _normalize_provider_frame(
            frame[["symbol", "date", "open", "high", "low", "close", "volume", "amount"]],
            "Tushare daily",
            normalize_daily_frame,
        )

    def fina_indicator(self, symbol: str) -> pd.DataFrame:
        checked_symbol = _valid_symbol(symbol)
        if self.rate_limiter:
            self.rate_limiter.consume("tushare")
        raw = self.client.fina_indicator(ts_code=checked_symbol)
        if raw is None or raw.empty:
            return pd.DataFrame(columns=["symbol", "period", "ann_date", "vintage"])
        rename = {
            "ts_code": "symbol",
            "end_date": "period",
            "roe_dt": "roe",
            "basic_eps": "eps",
            "bps": "bps",
            "or_yoy": "revenue_yoy",
            "netprofit_yoy": "profit_yoy",
            "debt_to_assets": "debt_ratio",
            "current_ratio": "current_ratio",
            "quick_ratio": "quick_ratio",
            "grossprofit_margin": "gross_margin",
            "netprofit_margin": "net_margin",
        }
        frame = raw.rename(columns=rename)
        if "ann_date" not in frame.columns:
            raise DataSourceError("Tushare fina_indicator missing ann_date")
        frame["vintage"] = frame.get("vintage", 0)
        keep = [
            "symbol",
            "period",
            "ann_date",
            "vintage",
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
        ]
        for column in keep:
            if column not in frame.columns:
                frame[column] = None
        return _normalize_provider_frame(frame[keep], "Tushare fina_indicator", normalize_financial_frame)
