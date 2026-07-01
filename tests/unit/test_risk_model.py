from datetime import date

import pandas as pd

from aeqcs.factor.risk_model import build_risk_model_snapshot, estimate_factor_returns


def risk_inputs():
    exposures = pd.DataFrame(
        [
            {"date": date(2026, 1, 1), "symbol": "A", "size": 1.0, "value": 0.0},
            {"date": date(2026, 1, 1), "symbol": "B", "size": 0.0, "value": 1.0},
            {"date": date(2026, 1, 1), "symbol": "C", "size": -1.0, "value": -1.0},
            {"date": date(2026, 1, 2), "symbol": "A", "size": 1.0, "value": 0.0},
            {"date": date(2026, 1, 2), "symbol": "B", "size": 0.0, "value": 1.0},
            {"date": date(2026, 1, 2), "symbol": "C", "size": -1.0, "value": -1.0},
        ]
    )
    returns = pd.DataFrame(
        [
            {"date": date(2026, 1, 1), "symbol": "A", "forward_return": 0.01},
            {"date": date(2026, 1, 1), "symbol": "B", "forward_return": 0.02},
            {"date": date(2026, 1, 1), "symbol": "C", "forward_return": -0.03},
            {"date": date(2026, 1, 2), "symbol": "A", "forward_return": 0.02},
            {"date": date(2026, 1, 2), "symbol": "B", "forward_return": 0.01},
            {"date": date(2026, 1, 2), "symbol": "C", "forward_return": -0.03},
        ]
    )
    return exposures, returns


def test_estimate_factor_returns_uses_cross_sectional_regression_by_date():
    exposures, returns = risk_inputs()

    factor_returns = estimate_factor_returns(exposures, returns, factor_columns=["size", "value"])

    assert factor_returns.round(6).to_dict("records") == [
        {"date": date(2026, 1, 1), "size": 0.01, "value": 0.02},
        {"date": date(2026, 1, 2), "size": 0.02, "value": 0.01},
    ]


def test_build_risk_model_snapshot_contains_covariance_and_specific_risk():
    exposures, returns = risk_inputs()
    factor_returns = estimate_factor_returns(exposures, returns, factor_columns=["size", "value"])

    snapshot = build_risk_model_snapshot(
        factor_returns=factor_returns,
        exposures=exposures,
        realized_returns=returns,
        factor_columns=["size", "value"],
        as_of_date=date(2026, 1, 2),
    )

    assert snapshot["as_of_date"] == date(2026, 1, 2)
    assert set(snapshot["factor_covariance"]) == {"size", "value"}
    assert set(snapshot["specific_risk"]) == {"A", "B", "C"}
