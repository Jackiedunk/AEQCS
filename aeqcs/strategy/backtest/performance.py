"""Backtest performance metrics."""

from __future__ import annotations

import pandas as pd


def max_drawdown(nav: pd.Series) -> float:
    peak = nav.cummax()
    dd = nav / peak - 1.0
    return float(dd.min())


def calculate_performance(nav: pd.Series, benchmark: pd.Series | None = None) -> dict[str, float]:
    returns = nav.pct_change().dropna()
    annual_return = float((nav.iloc[-1] / nav.iloc[0]) ** (252 / max(len(nav), 1)) - 1)
    volatility = float(returns.std() * (252**0.5)) if not returns.empty else 0.0
    sharpe = annual_return / volatility if volatility else 0.0
    result = {
        "annual_return": annual_return,
        "volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown(nav),
    }
    if benchmark is not None:
        result["excess_return"] = float(nav.pct_change().sub(benchmark.pct_change()).sum())
    return result
