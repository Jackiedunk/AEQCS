from datetime import date

import pandas as pd
import pytest

from aeqcs.core.exceptions import LookAheadViolation
from aeqcs.factor.evaluator import (
    qlib_icir_report,
    qlib_portfolio_optimizer,
    qlib_portfolio_optimization_report,
    qlib_risk_report,
)


def test_qlib_risk_report_standardizes_series_output():
    nav = pd.Series(
        [1.0, 1.02, 1.01],
        index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
        name="nav",
    )

    def fake_risk_analysis(series):
        assert series.equals(nav)
        return pd.Series({"annualized_return": 0.12, "max_drawdown": -0.03})

    report = qlib_risk_report(nav, as_of_date=date(2026, 1, 3), risk_analysis_fn=fake_risk_analysis)

    assert report == {
        "as_of_date": "2026-01-03",
        "metrics": {"annualized_return": 0.12, "max_drawdown": -0.03},
    }


def test_qlib_risk_report_rejects_future_nav_index():
    nav = pd.Series(
        [1.0, 1.02],
        index=pd.to_datetime(["2026-01-01", "2026-01-04"]),
        name="nav",
    )

    with pytest.raises(LookAheadViolation):
        qlib_risk_report(nav, as_of_date=date(2026, 1, 3), risk_analysis_fn=lambda series: pd.Series())


def test_qlib_risk_report_rejects_empty_nav():
    with pytest.raises(ValueError, match="NAV series is empty"):
        qlib_risk_report(pd.Series(dtype=float), as_of_date=date(2026, 1, 3))


def test_qlib_risk_report_rejects_invalid_nav_index():
    nav = pd.Series([1.0], index=["not-a-date"], name="nav")

    with pytest.raises(ValueError, match="date must be a valid date"):
        qlib_risk_report(nav, as_of_date=date(2026, 1, 3))


def test_qlib_risk_report_rejects_non_finite_nav_value():
    nav = pd.Series(
        [1.0, float("inf")],
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
        name="nav",
    )

    with pytest.raises(ValueError, match="nav must be finite"):
        qlib_risk_report(nav, as_of_date=date(2026, 1, 3))


def test_qlib_risk_report_rejects_non_finite_output_metric():
    nav = pd.Series(
        [1.0, 1.02],
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
        name="nav",
    )

    def fake_risk_analysis(series):
        return pd.Series({"annualized_return": float("inf")})

    with pytest.raises(ValueError, match="annualized_return must be finite"):
        qlib_risk_report(nav, as_of_date=date(2026, 1, 3), risk_analysis_fn=fake_risk_analysis)


def test_qlib_risk_report_rejects_empty_output_metrics():
    nav = pd.Series(
        [1.0, 1.02],
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
        name="nav",
    )

    def fake_risk_analysis(series):
        return pd.Series(dtype=float)

    with pytest.raises(ValueError, match="risk metrics are empty"):
        qlib_risk_report(nav, as_of_date=date(2026, 1, 3), risk_analysis_fn=fake_risk_analysis)


def test_qlib_risk_report_rejects_duplicate_output_metric_names():
    nav = pd.Series(
        [1.0, 1.02],
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
        name="nav",
    )

    def fake_risk_analysis(series):
        return pd.Series([0.12, 0.13], index=["annualized_return", "annualized_return"])

    with pytest.raises(ValueError, match="duplicate risk metric"):
        qlib_risk_report(nav, as_of_date=date(2026, 1, 3), risk_analysis_fn=fake_risk_analysis)


def test_qlib_risk_report_rejects_blank_output_metric_name():
    nav = pd.Series(
        [1.0, 1.02],
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
        name="nav",
    )

    def fake_risk_analysis(series):
        return pd.Series([0.12], index=[" "])

    with pytest.raises(ValueError, match="risk metric name is required"):
        qlib_risk_report(nav, as_of_date=date(2026, 1, 3), risk_analysis_fn=fake_risk_analysis)


def test_qlib_icir_report_standardizes_post_analysis_metrics():
    frame = pd.DataFrame(
        [
            {"date": "2026-01-01", "symbol": "000001", "factor": 1.0, "forward_return": 0.03},
            {"date": "2026-01-01", "symbol": "000002", "factor": 2.0, "forward_return": 0.05},
            {"date": "2026-01-02", "symbol": "000001", "factor": 3.0, "forward_return": 0.01},
            {"date": "2026-01-02", "symbol": "000002", "factor": 1.0, "forward_return": 0.04},
        ]
    )

    report = qlib_icir_report(frame, as_of_date=date(2026, 1, 2))

    assert report == {
        "as_of_date": "2026-01-02",
        "metrics": {"ic": 0.0, "icir": 0.0, "observations": 4.0, "dates": 2.0},
    }


def test_qlib_icir_report_rejects_future_rows():
    frame = pd.DataFrame(
        [
            {"date": "2026-01-04", "symbol": "000001", "factor": 1.0, "forward_return": 0.03},
        ]
    )

    with pytest.raises(LookAheadViolation):
        qlib_icir_report(frame, as_of_date=date(2026, 1, 3))


def test_qlib_icir_report_rejects_empty_symbol():
    frame = pd.DataFrame(
        [
            {"date": "2026-01-02", "symbol": " ", "factor": 1.0, "forward_return": 0.03},
        ]
    )

    with pytest.raises(ValueError, match="symbol is required"):
        qlib_icir_report(frame, as_of_date=date(2026, 1, 2))


def test_qlib_icir_report_rejects_invalid_date():
    frame = pd.DataFrame(
        [
            {"date": "not-a-date", "symbol": "000001", "factor": 1.0, "forward_return": 0.03},
        ]
    )

    with pytest.raises(ValueError, match="date must be a valid date"):
        qlib_icir_report(frame, as_of_date=date(2026, 1, 2))


def test_qlib_icir_report_rejects_duplicate_date_symbol_rows():
    frame = pd.DataFrame(
        [
            {"date": "2026-01-02", "symbol": "000001", "factor": 1.0, "forward_return": 0.03},
            {"date": "2026-01-02", "symbol": "000001", "factor": 2.0, "forward_return": 0.04},
        ]
    )

    with pytest.raises(ValueError, match="duplicate date/symbol"):
        qlib_icir_report(frame, as_of_date=date(2026, 1, 2))


def test_qlib_icir_report_rejects_non_finite_factor_value():
    frame = pd.DataFrame(
        [
            {"date": "2026-01-02", "symbol": "000001", "factor": float("nan"), "forward_return": 0.03},
        ]
    )

    with pytest.raises(ValueError, match="factor must be finite"):
        qlib_icir_report(frame, as_of_date=date(2026, 1, 2))


def test_qlib_icir_report_rejects_non_finite_forward_return_value():
    frame = pd.DataFrame(
        [
            {"date": "2026-01-02", "symbol": "000001", "factor": 1.0, "forward_return": float("inf")},
        ]
    )

    with pytest.raises(ValueError, match="forward_return must be finite"):
        qlib_icir_report(frame, as_of_date=date(2026, 1, 2))


def test_qlib_portfolio_optimization_report_standardizes_weights():
    alpha = pd.Series(
        [0.10, 0.20],
        index=pd.MultiIndex.from_tuples(
            [
                (pd.Timestamp("2026-01-02"), "000001"),
                (pd.Timestamp("2026-01-02"), "000002"),
            ],
            names=["date", "symbol"],
        ),
        name="alpha",
    )

    def fake_optimizer(series, risk_matrix=None):
        assert series.to_dict() == {"000001": 0.10, "000002": 0.20}
        assert risk_matrix is None
        return pd.Series({"000001": 0.4, "000002": 0.6})

    report = qlib_portfolio_optimization_report(
        alpha,
        as_of_date=date(2026, 1, 2),
        optimizer_fn=fake_optimizer,
    )

    assert report == {
        "as_of_date": "2026-01-02",
        "weights": {"000001": 0.4, "000002": 0.6},
        "metrics": {"gross_exposure": 1.0, "net_exposure": 1.0, "positions": 2.0},
    }


def test_qlib_portfolio_optimization_report_uses_default_long_only_optimizer():
    alpha = pd.Series(
        [0.10, -0.20, 0.30],
        index=pd.MultiIndex.from_tuples(
            [
                (pd.Timestamp("2026-01-02"), "000001"),
                (pd.Timestamp("2026-01-02"), "000002"),
                (pd.Timestamp("2026-01-02"), "000003"),
            ],
            names=["date", "symbol"],
        ),
        name="alpha",
    )

    report = qlib_portfolio_optimization_report(alpha, as_of_date=date(2026, 1, 2))

    assert report == {
        "as_of_date": "2026-01-02",
        "weights": {"000001": 0.25, "000003": 0.75},
        "metrics": {"gross_exposure": 1.0, "net_exposure": 1.0, "positions": 2.0},
    }


def test_qlib_portfolio_optimizer_rejects_alpha_without_positive_scores():
    alpha = pd.Series({"000001": 0.0, "000002": -0.10}, name="alpha")

    with pytest.raises(ValueError, match="optimization alpha has no positive scores"):
        qlib_portfolio_optimizer(alpha)


def test_qlib_portfolio_optimization_report_rejects_future_alpha():
    alpha = pd.Series(
        [0.10],
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-01-04"), "000001")],
            names=["date", "symbol"],
        ),
        name="alpha",
    )

    with pytest.raises(LookAheadViolation):
        qlib_portfolio_optimization_report(alpha, as_of_date=date(2026, 1, 3))


def test_qlib_portfolio_optimization_report_rejects_empty_symbol():
    alpha = pd.Series(
        [0.10],
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-01-02"), " ")],
            names=["date", "symbol"],
        ),
        name="alpha",
    )

    with pytest.raises(ValueError, match="symbol is required"):
        qlib_portfolio_optimization_report(alpha, as_of_date=date(2026, 1, 2))


def test_qlib_portfolio_optimization_report_rejects_invalid_date():
    alpha = pd.Series(
        [0.10],
        index=pd.MultiIndex.from_tuples(
            [("not-a-date", "000001")],
            names=["date", "symbol"],
        ),
        name="alpha",
    )

    with pytest.raises(ValueError, match="date must be a valid date"):
        qlib_portfolio_optimization_report(alpha, as_of_date=date(2026, 1, 2))


def test_qlib_portfolio_optimization_report_rejects_duplicate_date_symbol_alpha():
    alpha = pd.Series(
        [0.10, 0.20],
        index=pd.MultiIndex.from_tuples(
            [
                (pd.Timestamp("2026-01-02"), "000001"),
                (pd.Timestamp("2026-01-02"), "000001"),
            ],
            names=["date", "symbol"],
        ),
        name="alpha",
    )

    def fake_optimizer(series, risk_matrix=None):
        return pd.Series({"000001": 1.0})

    with pytest.raises(ValueError, match="duplicate date/symbol"):
        qlib_portfolio_optimization_report(
            alpha,
            as_of_date=date(2026, 1, 2),
            optimizer_fn=fake_optimizer,
        )


def test_qlib_portfolio_optimization_report_rejects_non_finite_alpha():
    alpha = pd.Series(
        [float("inf")],
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-01-02"), "000001")],
            names=["date", "symbol"],
        ),
        name="alpha",
    )

    with pytest.raises(ValueError, match="alpha must be finite"):
        qlib_portfolio_optimization_report(alpha, as_of_date=date(2026, 1, 2))


def test_qlib_portfolio_optimization_report_rejects_empty_output_symbol():
    alpha = pd.Series(
        [0.10],
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-01-02"), "000001")],
            names=["date", "symbol"],
        ),
        name="alpha",
    )

    def fake_optimizer(series, risk_matrix=None):
        return pd.Series({" ": 1.0})

    with pytest.raises(ValueError, match="symbol is required"):
        qlib_portfolio_optimization_report(
            alpha,
            as_of_date=date(2026, 1, 2),
            optimizer_fn=fake_optimizer,
        )


def test_qlib_portfolio_optimization_report_rejects_non_finite_output_weight():
    alpha = pd.Series(
        [0.10],
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-01-02"), "000001")],
            names=["date", "symbol"],
        ),
        name="alpha",
    )

    def fake_optimizer(series, risk_matrix=None):
        return pd.Series({"000001": float("inf")})

    with pytest.raises(ValueError, match="weight must be finite"):
        qlib_portfolio_optimization_report(
            alpha,
            as_of_date=date(2026, 1, 2),
            optimizer_fn=fake_optimizer,
        )


def test_qlib_portfolio_optimization_report_rejects_empty_output_weights():
    alpha = pd.Series(
        [0.10],
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-01-02"), "000001")],
            names=["date", "symbol"],
        ),
        name="alpha",
    )

    def fake_optimizer(series, risk_matrix=None):
        return pd.Series({"000001": float("nan")})

    with pytest.raises(ValueError, match="optimization weights are empty"):
        qlib_portfolio_optimization_report(
            alpha,
            as_of_date=date(2026, 1, 2),
            optimizer_fn=fake_optimizer,
        )


def test_qlib_portfolio_optimization_report_rejects_zero_gross_output_weights():
    alpha = pd.Series(
        [0.10],
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-01-02"), "000001")],
            names=["date", "symbol"],
        ),
        name="alpha",
    )

    def fake_optimizer(series, risk_matrix=None):
        return pd.Series({"000001": 0.0})

    with pytest.raises(ValueError, match="gross exposure is zero"):
        qlib_portfolio_optimization_report(
            alpha,
            as_of_date=date(2026, 1, 2),
            optimizer_fn=fake_optimizer,
        )


def test_qlib_portfolio_optimization_report_rejects_unknown_output_symbol():
    alpha = pd.Series(
        [0.10],
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-01-02"), "000001")],
            names=["date", "symbol"],
        ),
        name="alpha",
    )

    def fake_optimizer(series, risk_matrix=None):
        return pd.Series({"999999": 1.0})

    with pytest.raises(ValueError, match="unknown symbols"):
        qlib_portfolio_optimization_report(
            alpha,
            as_of_date=date(2026, 1, 2),
            optimizer_fn=fake_optimizer,
        )


def test_qlib_portfolio_optimization_report_rejects_duplicate_output_symbol():
    alpha = pd.Series(
        [0.10],
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2026-01-02"), "000001")],
            names=["date", "symbol"],
        ),
        name="alpha",
    )

    def fake_optimizer(series, risk_matrix=None):
        return pd.Series(
            [0.4, 0.6],
            index=["000001", "000001"],
        )

    with pytest.raises(ValueError, match="duplicate symbols"):
        qlib_portfolio_optimization_report(
            alpha,
            as_of_date=date(2026, 1, 2),
            optimizer_fn=fake_optimizer,
        )
