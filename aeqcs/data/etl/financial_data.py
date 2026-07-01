"""Financial PIT normalization helpers."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from aeqcs.core.versioning import (
    assert_not_after,
    require_as_of,
    require_date_value,
    require_finite_number,
    require_non_empty_text,
)

REQUIRED_FINANCIAL_COLUMNS = {"symbol", "period", "ann_date"}
FINANCIAL_ID_COLUMNS = {"symbol", "period", "ann_date", "vintage"}


def normalize_financial_frame(df: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_FINANCIAL_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"missing financial columns: {sorted(missing)}")
    out = df.copy()
    out["symbol"] = out["symbol"].map(lambda value: require_non_empty_text(value, "symbol"))
    out["period"] = out["period"].map(lambda value: require_non_empty_text(value, "period"))
    out["ann_date"] = out["ann_date"].map(lambda value: require_date_value(value, "ann_date"))
    if "vintage" not in out.columns:
        out["vintage"] = 0
    out["vintage"] = out["vintage"].map(lambda value: _require_non_negative_integer(value, "vintage"))
    for column in out.columns:
        if column not in FINANCIAL_ID_COLUMNS:
            out[column] = out[column].map(lambda value, field=column: _require_optional_finite_number(value, field))
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


def _require_non_negative_integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a non-negative integer")
    try:
        numeric = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a non-negative integer") from exc
    if not math.isfinite(numeric) or numeric < 0 or not numeric.is_integer():
        raise ValueError(f"{field} must be a non-negative integer")
    return int(numeric)


def _require_optional_finite_number(value: Any, field: str) -> Any:
    if value is None:
        return value
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, bool) and missing:
        return value
    return require_finite_number(value, field)
