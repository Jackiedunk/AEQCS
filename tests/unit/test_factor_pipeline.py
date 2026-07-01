from datetime import date, datetime

import pandas as pd
import pytest

from aeqcs.core.exceptions import LookAheadViolation
from aeqcs.factor.pipeline import compute_duckdb_factor_values


def daily_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"symbol": "000001", "date": date(2026, 1, 1), "close": 10.0},
            {"symbol": "000001", "date": date(2026, 1, 2), "close": 12.0},
            {"symbol": "000002", "date": date(2026, 1, 1), "close": 20.0},
            {"symbol": "000002", "date": date(2026, 1, 2), "close": 18.0},
            {"symbol": "000001", "date": date(2026, 1, 3), "close": 99.0},
        ]
    )


def test_duckdb_factor_pipeline_computes_standard_momentum_records(tmp_path):
    records = compute_duckdb_factor_values(
        daily_frame(),
        factor_ids=["momentum_1d"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        as_of_date=date(2026, 1, 2),
        temp_directory=tmp_path,
        memory_limit="256MB",
    )

    assert records == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 2),
            "factor_id": "momentum_1d",
            "version": 1,
            "value": 0.2,
            "calc_timestamp": datetime(2026, 1, 2),
        },
        {
            "symbol": "000002",
            "date": date(2026, 1, 2),
            "factor_id": "momentum_1d",
            "version": 1,
            "value": -0.1,
            "calc_timestamp": datetime(2026, 1, 2),
        },
    ]


def test_duckdb_factor_pipeline_computes_20_day_momentum(tmp_path):
    frame = pd.DataFrame(
        [
            {"symbol": "000001", "date": date(2026, 1, day), "close": float(day)}
            for day in range(1, 22)
        ]
    )

    records = compute_duckdb_factor_values(
        frame,
        factor_ids=["momentum_20d"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 21),
        as_of_date=date(2026, 1, 21),
        temp_directory=tmp_path,
    )

    assert records == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 21),
            "factor_id": "momentum_20d",
            "version": 1,
            "value": 20.0,
            "calc_timestamp": datetime(2026, 1, 21),
        }
    ]


def test_duckdb_factor_pipeline_rejects_lookahead_end_date(tmp_path):
    with pytest.raises(LookAheadViolation):
        compute_duckdb_factor_values(
            daily_frame(),
            factor_ids=["momentum_1d"],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 3),
            as_of_date=date(2026, 1, 2),
            temp_directory=tmp_path,
        )


def test_duckdb_factor_pipeline_rejects_unsupported_factor(tmp_path):
    with pytest.raises(ValueError, match="unsupported DuckDB factor ids"):
        compute_duckdb_factor_values(
            daily_frame(),
            factor_ids=["unknown_factor"],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
            as_of_date=date(2026, 1, 2),
            temp_directory=tmp_path,
        )


def test_duckdb_factor_pipeline_applies_cross_sectional_winsorize_and_zscore(tmp_path):
    frame = pd.DataFrame(
        [
            {"symbol": "000001", "date": date(2026, 1, 1), "close": 10.0},
            {"symbol": "000001", "date": date(2026, 1, 2), "close": 11.0},
            {"symbol": "000002", "date": date(2026, 1, 1), "close": 10.0},
            {"symbol": "000002", "date": date(2026, 1, 2), "close": 12.0},
            {"symbol": "000003", "date": date(2026, 1, 1), "close": 10.0},
            {"symbol": "000003", "date": date(2026, 1, 2), "close": 20.0},
        ]
    )

    records = compute_duckdb_factor_values(
        frame,
        factor_ids=["momentum_1d"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        as_of_date=date(2026, 1, 2),
        temp_directory=tmp_path,
        preprocess=["winsorize", "zscore"],
        winsorize_lower=0.25,
        winsorize_upper=0.75,
    )

    values = {record["symbol"]: record["value"] for record in records}
    assert values == pytest.approx(
        {
            "000001": -0.675737378399,
            "000002": -0.47301616488,
            "000003": 1.148753543279,
        }
    )


def test_duckdb_factor_pipeline_applies_industry_neutralize(tmp_path):
    frame = pd.DataFrame(
        [
            {"symbol": "000001", "date": date(2026, 1, 1), "close": 10.0, "industry": "bank"},
            {"symbol": "000001", "date": date(2026, 1, 2), "close": 11.0, "industry": "bank"},
            {"symbol": "000002", "date": date(2026, 1, 1), "close": 10.0, "industry": "bank"},
            {"symbol": "000002", "date": date(2026, 1, 2), "close": 13.0, "industry": "bank"},
            {"symbol": "000003", "date": date(2026, 1, 1), "close": 10.0, "industry": "tech"},
            {"symbol": "000003", "date": date(2026, 1, 2), "close": 12.0, "industry": "tech"},
            {"symbol": "000004", "date": date(2026, 1, 1), "close": 10.0, "industry": "tech"},
            {"symbol": "000004", "date": date(2026, 1, 2), "close": 14.0, "industry": "tech"},
        ]
    )

    records = compute_duckdb_factor_values(
        frame,
        factor_ids=["momentum_1d"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        as_of_date=date(2026, 1, 2),
        temp_directory=tmp_path,
        preprocess=["industry_neutralize"],
    )

    values = {record["symbol"]: record["value"] for record in records}
    assert values == pytest.approx(
        {
            "000001": -0.1,
            "000002": 0.1,
            "000003": -0.1,
            "000004": 0.1,
        }
    )


def test_duckdb_factor_pipeline_rejects_missing_industry_for_neutralize(tmp_path):
    with pytest.raises(ValueError, match="industry column is required"):
        compute_duckdb_factor_values(
            daily_frame(),
            factor_ids=["momentum_1d"],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
            as_of_date=date(2026, 1, 2),
            temp_directory=tmp_path,
            preprocess=["industry_neutralize"],
        )


def test_duckdb_factor_pipeline_applies_sector_neutralize(tmp_path):
    frame = pd.DataFrame(
        [
            {"symbol": "000001", "date": date(2026, 1, 1), "close": 10.0, "sector": "finance"},
            {"symbol": "000001", "date": date(2026, 1, 2), "close": 11.0, "sector": "finance"},
            {"symbol": "000002", "date": date(2026, 1, 1), "close": 10.0, "sector": "finance"},
            {"symbol": "000002", "date": date(2026, 1, 2), "close": 13.0, "sector": "finance"},
            {"symbol": "000003", "date": date(2026, 1, 1), "close": 10.0, "sector": "industrial"},
            {"symbol": "000003", "date": date(2026, 1, 2), "close": 12.0, "sector": "industrial"},
            {"symbol": "000004", "date": date(2026, 1, 1), "close": 10.0, "sector": "industrial"},
            {"symbol": "000004", "date": date(2026, 1, 2), "close": 14.0, "sector": "industrial"},
        ]
    )

    records = compute_duckdb_factor_values(
        frame,
        factor_ids=["momentum_1d"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        as_of_date=date(2026, 1, 2),
        temp_directory=tmp_path,
        preprocess=["sector_neutralize"],
    )

    values = {record["symbol"]: record["value"] for record in records}
    assert values == pytest.approx(
        {
            "000001": -0.1,
            "000002": 0.1,
            "000003": -0.1,
            "000004": 0.1,
        }
    )


def test_duckdb_factor_pipeline_rejects_missing_sector_for_neutralize(tmp_path):
    with pytest.raises(ValueError, match="sector column is required"):
        compute_duckdb_factor_values(
            daily_frame(),
            factor_ids=["momentum_1d"],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
            as_of_date=date(2026, 1, 2),
            temp_directory=tmp_path,
            preprocess=["sector_neutralize"],
        )


def test_duckdb_factor_pipeline_rejects_unknown_preprocess_step(tmp_path):
    with pytest.raises(ValueError, match="unsupported DuckDB preprocess steps"):
        compute_duckdb_factor_values(
            daily_frame(),
            factor_ids=["momentum_1d"],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
            as_of_date=date(2026, 1, 2),
            temp_directory=tmp_path,
            preprocess=["unknown_step"],
        )
