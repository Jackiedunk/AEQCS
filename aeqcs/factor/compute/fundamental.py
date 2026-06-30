"""Fundamental factor helpers."""

from __future__ import annotations

import pandas as pd


def latest_pit_values(df: pd.DataFrame, as_of_date) -> pd.DataFrame:
    filtered = df[df["ann_date"] <= as_of_date].copy()
    if filtered.empty:
        return filtered
    return filtered.sort_values(["symbol", "period", "ann_date", "vintage"]).groupby(
        ["symbol", "period"], as_index=False
    ).tail(1)
