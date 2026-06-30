"""Technical factor computations over daily bar panels."""

from __future__ import annotations

import pandas as pd


def momentum(close: pd.Series, window: int) -> pd.Series:
    return close / close.shift(window) - 1.0


def rolling_volatility(close: pd.Series, window: int) -> pd.Series:
    return close.pct_change().rolling(window).std()


def compute_panel_momentum(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    required = {"symbol", "date", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    out = df.sort_values(["symbol", "date"]).copy()
    out[f"momentum_{window}d"] = out.groupby("symbol")["close"].transform(
        lambda close: momentum(close, window)
    )
    return out[["symbol", "date", f"momentum_{window}d"]]
