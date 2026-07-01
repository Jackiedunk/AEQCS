"""Bounded production factor pipelines."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from aeqcs.core.versioning import assert_not_after, require_as_of


DUCKDB_FACTOR_WINDOWS = {"momentum_1d": 1, "momentum_20d": 20}
DUCKDB_SUPPORTED_FACTORS = set(DUCKDB_FACTOR_WINDOWS)
DUCKDB_SUPPORTED_PREPROCESS = {"winsorize", "zscore", "industry_neutralize", "sector_neutralize"}


def compute_duckdb_factor_values(
    daily: pd.DataFrame,
    *,
    factor_ids: list[str],
    start_date: date,
    end_date: date,
    as_of_date: date | None,
    temp_directory: str | Path,
    memory_limit: str = "1GB",
    version: int = 1,
    preprocess: list[str] | None = None,
    winsorize_lower: float = 0.01,
    winsorize_upper: float = 0.99,
) -> list[dict[str, Any]]:
    checked_as_of = require_as_of(as_of_date)
    assert_not_after(end_date, checked_as_of)
    unknown = set(factor_ids) - DUCKDB_SUPPORTED_FACTORS
    if unknown:
        raise ValueError(f"unsupported DuckDB factor ids: {sorted(unknown)}")
    steps = preprocess or []
    unsupported_steps = set(steps) - DUCKDB_SUPPORTED_PREPROCESS
    if unsupported_steps:
        raise ValueError(f"unsupported DuckDB preprocess steps: {sorted(unsupported_steps)}")
    if "industry_neutralize" in steps and "industry" not in daily.columns:
        raise ValueError("industry column is required for industry_neutralize")
    if "sector_neutralize" in steps and "sector" not in daily.columns:
        raise ValueError("sector column is required for sector_neutralize")
    if daily.empty or not factor_ids:
        return []

    columns = ["symbol", "date", "close"]
    if "industry" in daily.columns:
        columns.append("industry")
    if "sector" in daily.columns:
        columns.append("sector")
    frame = daily[columns].copy()
    frame["symbol"] = frame["symbol"].astype(str)
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    if "industry" not in frame.columns:
        frame["industry"] = ""
    if "sector" not in frame.columns:
        frame["sector"] = ""
    frame["industry"] = frame["industry"].astype(str)
    frame["sector"] = frame["sector"].astype(str)

    temp_path = Path(temp_directory)
    temp_path.mkdir(parents=True, exist_ok=True)
    calc_timestamp = datetime.combine(checked_as_of, datetime.min.time())

    with duckdb.connect(database=":memory:") as conn:
        conn.execute(f"SET memory_limit = '{memory_limit}'")
        conn.execute("SET temp_directory = ?", [str(temp_path)])
        conn.register("daily", frame)
        outputs: list[dict[str, Any]] = []
        for factor_id in factor_ids:
            window = DUCKDB_FACTOR_WINDOWS[factor_id]
            rows = conn.execute(
                """
                WITH scoped AS (
                    SELECT
                        symbol,
                        date,
                        close,
                        industry,
                        sector,
                        lag(close, ?) OVER (PARTITION BY symbol ORDER BY date) AS prev_close
                    FROM daily
                    WHERE date <= ?
                ),
                raw_values AS (
                    SELECT
                        symbol,
                        date,
                        industry,
                        sector,
                        ? AS factor_id,
                        ? AS version,
                        close / prev_close - 1.0 AS raw_value
                    FROM scoped
                    WHERE date >= ?
                      AND date <= ?
                      AND prev_close IS NOT NULL
                ),
                winsor_bounds AS (
                    SELECT
                        date,
                        factor_id,
                        quantile_cont(raw_value, ?) AS lower_bound,
                        quantile_cont(raw_value, ?) AS upper_bound
                    FROM raw_values
                    GROUP BY date, factor_id
                ),
                winsorized AS (
                    SELECT
                        raw_values.symbol,
                        raw_values.date,
                        raw_values.industry,
                        raw_values.sector,
                        raw_values.factor_id,
                        raw_values.version,
                        CASE
                            WHEN ? THEN least(
                                greatest(raw_values.raw_value, winsor_bounds.lower_bound),
                                winsor_bounds.upper_bound
                            )
                            ELSE raw_values.raw_value
                        END AS value
                    FROM raw_values
                    JOIN winsor_bounds USING (date, factor_id)
                ),
                industry_neutralized AS (
                    SELECT
                        symbol,
                        date,
                        industry,
                        sector,
                        factor_id,
                        version,
                        CASE
                            WHEN ?
                            THEN value - avg(value) OVER (PARTITION BY date, factor_id, industry)
                            ELSE value
                        END AS value
                    FROM winsorized
                ),
                sector_neutralized AS (
                    SELECT
                        symbol,
                        date,
                        industry,
                        sector,
                        factor_id,
                        version,
                        CASE
                            WHEN ?
                            THEN value - avg(value) OVER (PARTITION BY date, factor_id, sector)
                            ELSE value
                        END AS value
                    FROM industry_neutralized
                ),
                standardized AS (
                    SELECT
                        symbol,
                        date,
                        factor_id,
                        version,
                        CASE
                            WHEN ? AND stddev_samp(value) OVER (PARTITION BY date, factor_id) > 0
                            THEN (
                                value - avg(value) OVER (PARTITION BY date, factor_id)
                            ) / stddev_samp(value) OVER (PARTITION BY date, factor_id)
                            ELSE value
                        END AS value
                    FROM sector_neutralized
                )
                SELECT
                    symbol,
                    date,
                    factor_id,
                    version,
                    value
                FROM standardized
                ORDER BY factor_id, symbol, date
                """,
                [
                    window,
                    checked_as_of,
                    factor_id,
                    version,
                    start_date,
                    end_date,
                    winsorize_lower,
                    winsorize_upper,
                    "winsorize" in steps,
                    "industry_neutralize" in steps,
                    "sector_neutralize" in steps,
                    "zscore" in steps,
                ],
            ).fetchall()
            outputs.extend(
                {
                    "symbol": symbol,
                    "date": row_date,
                    "factor_id": factor_id,
                    "version": row_version,
                    "value": round(float(value), 12),
                    "calc_timestamp": calc_timestamp,
                }
                for symbol, row_date, factor_id, row_version, value in rows
            )
    return outputs
