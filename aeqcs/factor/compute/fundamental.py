"""Fundamental factor helpers."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import pandas as pd

from aeqcs.core.versioning import assert_not_after, require_as_of


def latest_pit_values(df: pd.DataFrame, as_of_date) -> pd.DataFrame:
    filtered = df[df["ann_date"] <= as_of_date].copy()
    if filtered.empty:
        return filtered
    return filtered.sort_values(["symbol", "period", "ann_date", "vintage"]).groupby(
        ["symbol", "period"], as_index=False
    ).tail(1)


def _compute_quarterly_financial_values(
    financials: pd.DataFrame,
    *,
    factor_id: str,
    value_column: str,
    start_date: date,
    end_date: date,
    as_of_date: date | None,
    version: int = 1,
) -> list[dict[str, Any]]:
    checked_as_of = require_as_of(as_of_date)
    if not isinstance(checked_as_of, date):
        raise ValueError("as_of_date must be a date")
    assert_not_after(end_date, checked_as_of)
    if financials.empty:
        return []
    required = {"symbol", "period", "ann_date", "vintage", value_column}
    missing = required - set(financials.columns)
    if missing:
        raise ValueError(f"{factor_id} financials missing columns: {sorted(missing)}")

    frame = financials.copy()
    frame["symbol"] = frame["symbol"].astype(str)
    frame["period"] = frame["period"].astype(str)
    frame["ann_date"] = pd.to_datetime(frame["ann_date"]).dt.date
    scoped = frame[
        (frame["ann_date"] >= start_date)
        & (frame["ann_date"] <= end_date)
        & (frame["ann_date"] <= checked_as_of)
    ].copy()
    if scoped.empty:
        return []

    latest = latest_pit_values(scoped, checked_as_of)
    calc_timestamp = datetime.combine(checked_as_of, datetime.min.time())
    rows = latest.dropna(subset=[value_column]).sort_values(["symbol", "period"]).to_dict("records")
    return [
        {
            "symbol": row["symbol"],
            "date": row["ann_date"],
            "factor_id": factor_id,
            "version": version,
            "value": round(float(row[value_column]), 12),
            "calc_timestamp": calc_timestamp,
        }
        for row in rows
    ]


def compute_roe_quarterly_values(
    financials: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    as_of_date: date | None,
    version: int = 1,
) -> list[dict[str, Any]]:
    return _compute_quarterly_financial_values(
        financials,
        factor_id="roe_quarterly",
        value_column="roe",
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        version=version,
    )


def compute_debt_ratio_quarterly_values(
    financials: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    as_of_date: date | None,
    version: int = 1,
) -> list[dict[str, Any]]:
    return _compute_quarterly_financial_values(
        financials,
        factor_id="debt_ratio_quarterly",
        value_column="debt_ratio",
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        version=version,
    )


def compute_equity_ratio_quarterly_values(
    financials: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    as_of_date: date | None,
    version: int = 1,
) -> list[dict[str, Any]]:
    rows = _compute_quarterly_financial_values(
        financials,
        factor_id="equity_ratio_quarterly",
        value_column="debt_ratio",
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        version=version,
    )
    for row in rows:
        row["value"] = round(1.0 - row["value"], 12)
    return rows


def compute_debt_to_equity_quarterly_values(
    financials: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    as_of_date: date | None,
    version: int = 1,
) -> list[dict[str, Any]]:
    rows = _compute_quarterly_financial_values(
        financials,
        factor_id="debt_to_equity_quarterly",
        value_column="debt_ratio",
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        version=version,
    )
    transformed: list[dict[str, Any]] = []
    for row in rows:
        debt_ratio = float(row["value"])
        equity_ratio = 1.0 - debt_ratio
        if equity_ratio <= 0:
            continue
        value = debt_ratio / equity_ratio
        if not math.isfinite(value):
            continue
        row["value"] = round(value, 12)
        transformed.append(row)
    return transformed


def compute_profit_yoy_quarterly_values(
    financials: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    as_of_date: date | None,
    version: int = 1,
) -> list[dict[str, Any]]:
    return _compute_quarterly_financial_values(
        financials,
        factor_id="profit_yoy_quarterly",
        value_column="profit_yoy",
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        version=version,
    )


def compute_current_ratio_quarterly_values(
    financials: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    as_of_date: date | None,
    version: int = 1,
) -> list[dict[str, Any]]:
    return _compute_quarterly_financial_values(
        financials,
        factor_id="current_ratio_quarterly",
        value_column="current_ratio",
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        version=version,
    )


def compute_quick_ratio_quarterly_values(
    financials: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    as_of_date: date | None,
    version: int = 1,
) -> list[dict[str, Any]]:
    return _compute_quarterly_financial_values(
        financials,
        factor_id="quick_ratio_quarterly",
        value_column="quick_ratio",
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        version=version,
    )


def compute_revenue_yoy_quarterly_values(
    financials: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    as_of_date: date | None,
    version: int = 1,
) -> list[dict[str, Any]]:
    return _compute_quarterly_financial_values(
        financials,
        factor_id="revenue_yoy_quarterly",
        value_column="revenue_yoy",
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        version=version,
    )


def compute_eps_quarterly_values(
    financials: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    as_of_date: date | None,
    version: int = 1,
) -> list[dict[str, Any]]:
    return _compute_quarterly_financial_values(
        financials,
        factor_id="eps_quarterly",
        value_column="eps",
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        version=version,
    )


def compute_bps_quarterly_values(
    financials: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    as_of_date: date | None,
    version: int = 1,
) -> list[dict[str, Any]]:
    return _compute_quarterly_financial_values(
        financials,
        factor_id="bps_quarterly",
        value_column="bps",
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        version=version,
    )


def compute_gross_margin_quarterly_values(
    financials: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    as_of_date: date | None,
    version: int = 1,
) -> list[dict[str, Any]]:
    return _compute_quarterly_financial_values(
        financials,
        factor_id="gross_margin_quarterly",
        value_column="gross_margin",
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        version=version,
    )


def compute_net_margin_quarterly_values(
    financials: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    as_of_date: date | None,
    version: int = 1,
) -> list[dict[str, Any]]:
    return _compute_quarterly_financial_values(
        financials,
        factor_id="net_margin_quarterly",
        value_column="net_margin",
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
        version=version,
    )


def compute_margin_spread_quarterly_values(
    financials: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    as_of_date: date | None,
    version: int = 1,
) -> list[dict[str, Any]]:
    checked_as_of = require_as_of(as_of_date)
    if not isinstance(checked_as_of, date):
        raise ValueError("as_of_date must be a date")
    assert_not_after(end_date, checked_as_of)
    if financials.empty:
        return []
    required = {"symbol", "period", "ann_date", "vintage", "gross_margin", "net_margin"}
    missing = required - set(financials.columns)
    if missing:
        raise ValueError(f"margin_spread_quarterly financials missing columns: {sorted(missing)}")

    frame = financials.copy()
    frame["symbol"] = frame["symbol"].astype(str)
    frame["period"] = frame["period"].astype(str)
    frame["ann_date"] = pd.to_datetime(frame["ann_date"]).dt.date
    scoped = frame[
        (frame["ann_date"] >= start_date)
        & (frame["ann_date"] <= end_date)
        & (frame["ann_date"] <= checked_as_of)
    ].copy()
    if scoped.empty:
        return []

    latest = latest_pit_values(scoped, checked_as_of)
    calc_timestamp = datetime.combine(checked_as_of, datetime.min.time())
    rows = latest.dropna(subset=["gross_margin", "net_margin"]).sort_values(["symbol", "period"]).to_dict("records")
    outputs: list[dict[str, Any]] = []
    for row in rows:
        value = float(row["gross_margin"]) - float(row["net_margin"])
        if not math.isfinite(value):
            continue
        outputs.append(
            {
                "symbol": row["symbol"],
                "date": row["ann_date"],
                "factor_id": "margin_spread_quarterly",
                "version": version,
                "value": round(value, 12),
                "calc_timestamp": calc_timestamp,
            }
        )
    return outputs
