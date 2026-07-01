"""Deterministic multi-factor risk model helpers."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from aeqcs.core.versioning import assert_not_after, require_date_value


def _require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{name} missing columns: {sorted(missing)}")


def estimate_factor_returns(
    exposures: pd.DataFrame,
    realized_returns: pd.DataFrame,
    *,
    factor_columns: list[str],
) -> pd.DataFrame:
    if not factor_columns:
        raise ValueError("factor_columns is required")
    _require_columns(exposures, {"date", "symbol", *factor_columns}, "exposures")
    _require_columns(realized_returns, {"date", "symbol", "forward_return"}, "realized_returns")

    merged = exposures.merge(realized_returns, on=["date", "symbol"], how="inner")
    rows: list[dict[str, Any]] = []
    for current_date, group in merged.groupby("date", sort=True):
        if len(group) < len(factor_columns):
            continue
        x = group[factor_columns].astype(float).to_numpy()
        y = group["forward_return"].astype(float).to_numpy()
        coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
        rows.append(
            {
                "date": current_date,
                **{factor: float(coefficients[index]) for index, factor in enumerate(factor_columns)},
            }
        )
    return pd.DataFrame(rows, columns=["date", *factor_columns])


def _residuals(
    exposures: pd.DataFrame,
    realized_returns: pd.DataFrame,
    factor_returns: pd.DataFrame,
    factor_columns: list[str],
) -> pd.DataFrame:
    merged = exposures.merge(realized_returns, on=["date", "symbol"], how="inner")
    merged = merged.merge(factor_returns, on="date", how="inner", suffixes=("_exposure", "_return"))
    predicted = np.zeros(len(merged))
    for factor in factor_columns:
        predicted += merged[factor + "_exposure"].astype(float).to_numpy() * merged[factor + "_return"].astype(float).to_numpy()
    merged["residual"] = merged["forward_return"].astype(float) - predicted
    return merged[["date", "symbol", "residual"]]


def build_risk_model_snapshot(
    *,
    factor_returns: pd.DataFrame,
    exposures: pd.DataFrame,
    realized_returns: pd.DataFrame,
    factor_columns: list[str],
    as_of_date: date,
) -> dict[str, Any]:
    checked_as_of = require_date_value(as_of_date, "as_of_date")
    if factor_returns.empty:
        raise ValueError("factor_returns is required")
    latest_date = require_date_value(factor_returns["date"].max(), "date")
    assert_not_after(latest_date, checked_as_of)
    _require_columns(factor_returns, {"date", *factor_columns}, "factor_returns")

    covariance = factor_returns[factor_columns].astype(float).cov().fillna(0.0)
    residual_frame = _residuals(exposures, realized_returns, factor_returns, factor_columns)
    specific = residual_frame.groupby("symbol")["residual"].std().fillna(0.0)
    return {
        "as_of_date": checked_as_of,
        "factor_returns": factor_returns.to_dict("records"),
        "factor_covariance": covariance.to_dict(),
        "specific_risk": {symbol: float(value) for symbol, value in specific.items()},
    }
