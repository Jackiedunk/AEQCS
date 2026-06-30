"""Alternative data factor helpers."""

from __future__ import annotations

import pandas as pd


def concept_heat(cooccurrence: pd.DataFrame, price_correlation: pd.DataFrame) -> pd.DataFrame:
    merged = cooccurrence.merge(price_correlation, on=["concept", "symbol"], how="inner")
    merged["concept_heat"] = merged["frequency"] * merged["price_correlation"]
    return merged[["concept", "symbol", "date", "concept_heat"]]
