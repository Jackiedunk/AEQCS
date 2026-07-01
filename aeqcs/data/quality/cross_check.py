"""Cross-source market data consistency checks."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd


def _relative_diff(left: float, right: float) -> float:
    denominator = max(abs(left), 1.0)
    return abs(left - right) / denominator


def _alert(
    *,
    row: pd.Series,
    metric: str,
    primary_source: str,
    cross_check_source: str,
    primary_value: float,
    cross_check_value: float,
    relative_diff: float,
    tolerance: float,
) -> dict[str, Any]:
    return {
        "alert_type": "daily_cross_check_mismatch",
        "severity": "warning",
        "source": "data_quality.cross_check",
        "primary_source": primary_source,
        "cross_check_source": cross_check_source,
        "symbol": row["symbol"],
        "date": row["date"],
        "metric": metric,
        "primary_value": primary_value,
        "cross_check_value": cross_check_value,
        "relative_diff": relative_diff,
        "tolerance": tolerance,
        "created_at": datetime.utcnow(),
    }


def compare_daily_bars(
    *,
    primary: pd.DataFrame,
    cross_check: pd.DataFrame,
    primary_source: str,
    cross_check_source: str,
    close_tolerance: float,
    volume_tolerance: float,
) -> list[dict[str, Any]]:
    """Compare same-day daily close and volume across two providers.

    The returned records are intended for the data quality alert log rather than
    proposal review; these are deterministic source-integrity findings.
    """

    required = {"symbol", "date", "close", "volume"}
    missing_primary = required - set(primary.columns)
    missing_cross = required - set(cross_check.columns)
    if missing_primary:
        raise ValueError(f"primary missing columns: {sorted(missing_primary)}")
    if missing_cross:
        raise ValueError(f"cross_check missing columns: {sorted(missing_cross)}")

    left = primary[list(required)].copy()
    right = cross_check[list(required)].copy()
    merged = left.merge(
        right,
        on=["symbol", "date"],
        how="inner",
        suffixes=("_primary", "_cross_check"),
    ).sort_values(["symbol", "date"])

    alerts: list[dict[str, Any]] = []
    for _, row in merged.iterrows():
        close_primary = float(row["close_primary"])
        close_cross = float(row["close_cross_check"])
        close_diff = _relative_diff(close_primary, close_cross)
        if close_diff > close_tolerance:
            alerts.append(
                _alert(
                    row=row,
                    metric="close",
                    primary_source=primary_source,
                    cross_check_source=cross_check_source,
                    primary_value=close_primary,
                    cross_check_value=close_cross,
                    relative_diff=close_diff,
                    tolerance=close_tolerance,
                )
            )

        volume_primary = float(row["volume_primary"])
        volume_cross = float(row["volume_cross_check"])
        volume_diff = _relative_diff(volume_primary, volume_cross)
        if volume_diff > volume_tolerance:
            alerts.append(
                _alert(
                    row=row,
                    metric="volume",
                    primary_source=primary_source,
                    cross_check_source=cross_check_source,
                    primary_value=volume_primary,
                    cross_check_value=volume_cross,
                    relative_diff=volume_diff,
                    tolerance=volume_tolerance,
                )
            )
    return alerts
