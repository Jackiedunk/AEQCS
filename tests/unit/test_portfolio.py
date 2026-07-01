from decimal import Decimal

import pytest

from aeqcs.strategy import portfolio


def test_portfolio_market_value_includes_cash_and_positions() -> None:
    account = portfolio.Portfolio(
        cash=Decimal("100"),
        positions={"AAA": 10, "BBB": 5},
    )

    assert account.market_value({"AAA": Decimal("12"), "BBB": Decimal("8")}) == Decimal("260")


def test_scan_portfolio_risk_emits_exposure_and_concentration_alerts() -> None:
    assert hasattr(portfolio, "scan_portfolio_risk")

    account = portfolio.Portfolio(
        cash=Decimal("0"),
        positions={"AAA": 80, "BBB": 20},
    )
    report = portfolio.scan_portfolio_risk(
        account,
        {"AAA": Decimal("10"), "BBB": Decimal("10")},
        max_gross_exposure=Decimal("0.80"),
        max_single_position_weight=Decimal("0.50"),
    )

    assert report == {
        "status": "red",
        "metrics": {
            "nav": Decimal("1000"),
            "gross_exposure": Decimal("1"),
            "net_exposure": Decimal("1"),
            "max_position_weight": Decimal("0.8"),
            "max_position_symbol": "AAA",
        },
        "alerts": [
            {
                "severity": "red",
                "action": "risk_officer.reduce_exposure",
                "metric": "gross_exposure",
                "value": Decimal("1"),
                "threshold": Decimal("0.80"),
            },
            {
                "severity": "red",
                "action": "risk_officer.review_concentration",
                "metric": "single_position_weight",
                "symbol": "AAA",
                "value": Decimal("0.8"),
                "threshold": Decimal("0.50"),
            },
        ],
    }


def test_scan_portfolio_risk_stays_ok_within_limits() -> None:
    assert hasattr(portfolio, "scan_portfolio_risk")

    account = portfolio.Portfolio(
        cash=Decimal("500"),
        positions={"AAA": 50},
    )
    report = portfolio.scan_portfolio_risk(
        account,
        {"AAA": Decimal("10")},
        max_gross_exposure=Decimal("0.80"),
        max_single_position_weight=Decimal("0.60"),
    )

    assert report == {
        "status": "ok",
        "metrics": {
            "nav": Decimal("1000"),
            "gross_exposure": Decimal("0.5"),
            "net_exposure": Decimal("0.5"),
            "max_position_weight": Decimal("0.5"),
            "max_position_symbol": "AAA",
        },
        "alerts": [],
    }


def test_scan_portfolio_risk_rejects_invalid_thresholds() -> None:
    account = portfolio.Portfolio(cash=Decimal("100"), positions={"AAA": 1})
    prices = {"AAA": Decimal("10")}

    with pytest.raises(ValueError, match="max_gross_exposure must be non-negative"):
        portfolio.scan_portfolio_risk(account, prices, max_gross_exposure=Decimal("-0.1"))

    with pytest.raises(ValueError, match="max_single_position_weight must be finite"):
        portfolio.scan_portfolio_risk(account, prices, max_single_position_weight=Decimal("NaN"))


def test_optimize_risk_constrained_weights_respects_position_and_industry_limits() -> None:
    weights = portfolio.optimize_risk_constrained_weights(
        scores={"000001": 0.10, "000002": 0.02, "000003": 0.01},
        covariance=[
            [0.04, 0.00, 0.00],
            [0.00, 0.02, 0.00],
            [0.00, 0.00, 0.02],
        ],
        symbols=["000001", "000002", "000003"],
        industries={"000001": "bank", "000002": "bank", "000003": "tech"},
        max_position_weight=0.6,
        max_industry_weight=0.7,
        max_variance=0.03,
    )

    assert round(sum(weights.values()), 6) == 1.0
    assert weights["000001"] <= 0.6 + 1e-6
    assert weights["000001"] + weights["000002"] <= 0.7 + 1e-6
