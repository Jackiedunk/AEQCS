"""Price adjustment helpers."""

from __future__ import annotations

import pandas as pd

PRICE_COLUMNS = ("open", "high", "low", "close")


def apply_backward_adjustment(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply append-safe backward adjustment using first observed adj_factor as base."""
    required = {"symbol", "date", "adj_factor", *PRICE_COLUMNS}
    missing = required - set(frame.columns)
    if "adj_factor" in missing:
        raise ValueError("adj_factor column is required for backward adjustment")
    if missing:
        raise ValueError(f"price adjustment frame missing columns: {sorted(missing)}")
    if frame.empty:
        return frame.copy()

    adjusted = frame.copy()
    adjusted["symbol"] = adjusted["symbol"].astype(str)
    adjusted["date"] = pd.to_datetime(adjusted["date"]).dt.date
    adjusted["adj_factor"] = pd.to_numeric(adjusted["adj_factor"])
    adjusted = adjusted.sort_values(["symbol", "date"]).reset_index(drop=True)
    base = adjusted.groupby("symbol", sort=False)["adj_factor"].transform("first")
    if (base == 0).any():
        raise ValueError("base adj_factor cannot be zero")
    ratio = adjusted["adj_factor"] / base
    for column in PRICE_COLUMNS:
        adjusted[column] = pd.to_numeric(adjusted[column])
        adjusted[f"hfq_{column}"] = (adjusted[column] * ratio).round(12)
    return adjusted


def apply_dual_price_adjustment(frame: pd.DataFrame) -> pd.DataFrame:
    """Add HFQ storage prices and QFQ display prices from system adj_factor values."""
    adjusted = apply_backward_adjustment(frame)
    latest = adjusted.groupby("symbol", sort=False)["adj_factor"].transform("last")
    if (latest == 0).any():
        raise ValueError("latest adj_factor cannot be zero")
    ratio = adjusted["adj_factor"] / latest
    for column in PRICE_COLUMNS:
        adjusted[f"qfq_{column}"] = (pd.to_numeric(adjusted[column]) * ratio).round(12)
    return adjusted
