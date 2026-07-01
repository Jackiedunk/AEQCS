"""Outlier detection for canonical market data frames."""

from __future__ import annotations

from typing import Any

import pandas as pd


def detect_daily_outliers(df: pd.DataFrame, *, max_abs_return: float = 0.25) -> list[dict[str, Any]]:
    required = {"symbol", "date", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"daily outlier input missing columns: {sorted(missing)}")
    if max_abs_return <= 0:
        raise ValueError("max_abs_return must be positive")

    frame = df[["symbol", "date", "close"]].copy()
    frame["close"] = pd.to_numeric(frame["close"])
    frame = frame.sort_values(["symbol", "date"]).reset_index(drop=True)
    frame["previous_close"] = frame.groupby("symbol")["close"].shift(1)
    frame = frame.dropna(subset=["previous_close"])
    frame["close_return"] = (frame["close"] - frame["previous_close"]) / frame["previous_close"]

    alerts: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        value = float(row["close_return"])
        if abs(value) > max_abs_return:
            alerts.append(
                {
                    "alert_type": "daily_outlier",
                    "severity": "warning",
                    "symbol": row["symbol"],
                    "date": row["date"],
                    "metric": "close_return",
                    "value": value,
                    "threshold": max_abs_return,
                }
            )
    return alerts
