"""Financial PIT normalization helpers."""

from __future__ import annotations

import pandas as pd

from aeqcs.core.versioning import assert_not_after, require_as_of

REQUIRED_FINANCIAL_COLUMNS = {"symbol", "period", "ann_date"}


def normalize_financial_frame(df: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_FINANCIAL_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"missing financial columns: {sorted(missing)}")
    out = df.copy()
    out["symbol"] = out["symbol"].astype(str)
    out["period"] = out["period"].astype(str)
    out["ann_date"] = pd.to_datetime(out["ann_date"]).dt.date
    if "vintage" not in out.columns:
        out["vintage"] = 0
    return out.sort_values(["symbol", "period", "ann_date", "vintage"]).reset_index(drop=True)


def pit_slice(df: pd.DataFrame, symbol: str, period: str, as_of_date) -> dict:
    require_as_of(as_of_date)
    normalized = normalize_financial_frame(df)
    subset = normalized[
        (normalized["symbol"] == symbol)
        & (normalized["period"] == period)
        & (normalized["ann_date"] <= as_of_date)
    ].sort_values(["ann_date", "vintage"])
    if subset.empty:
        return {}
    row = subset.iloc[-1].to_dict()
    assert_not_after(row["ann_date"], as_of_date)
    return row
