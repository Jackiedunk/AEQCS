"""Simple long-only portfolio accounting."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Sequence, TypedDict


class PortfolioRiskMetrics(TypedDict):
    nav: Decimal
    gross_exposure: Decimal
    net_exposure: Decimal
    max_position_weight: Decimal
    max_position_symbol: str | None


class PortfolioRiskAlert(TypedDict, total=False):
    severity: Literal["red"]
    action: Literal["risk_officer.reduce_exposure", "risk_officer.review_concentration"]
    metric: Literal["gross_exposure", "single_position_weight"]
    symbol: str
    value: Decimal
    threshold: Decimal


class PortfolioRiskReport(TypedDict):
    status: Literal["ok", "red"]
    metrics: PortfolioRiskMetrics
    alerts: list[PortfolioRiskAlert]


@dataclass(slots=True)
class Portfolio:
    cash: Decimal
    positions: dict[str, int] = field(default_factory=dict)

    def market_value(self, prices: dict[str, Decimal]) -> Decimal:
        value = self.cash
        for symbol, quantity in self.positions.items():
            value += prices.get(symbol, Decimal("0")) * quantity
        return value

    def apply_fill(self, symbol: str, quantity: int, price: Decimal, fee: Decimal = Decimal("0")) -> None:
        self.cash -= Decimal(quantity) * price + fee
        self.positions[symbol] = self.positions.get(symbol, 0) + quantity

    def position_values(self, prices: dict[str, Decimal]) -> dict[str, Decimal]:
        return {
            symbol: prices.get(symbol, Decimal("0")) * Decimal(quantity)
            for symbol, quantity in self.positions.items()
        }


def _require_non_negative_finite_threshold(value: Decimal, name: str) -> Decimal:
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def scan_portfolio_risk(
    portfolio: Portfolio,
    prices: dict[str, Decimal],
    *,
    max_gross_exposure: Decimal = Decimal("1"),
    max_single_position_weight: Decimal = Decimal("0.30"),
) -> PortfolioRiskReport:
    max_gross_exposure = _require_non_negative_finite_threshold(max_gross_exposure, "max_gross_exposure")
    max_single_position_weight = _require_non_negative_finite_threshold(
        max_single_position_weight,
        "max_single_position_weight",
    )
    position_values = portfolio.position_values(prices)
    nav = portfolio.cash + sum(position_values.values(), Decimal("0"))

    gross_position_value = sum((abs(value) for value in position_values.values()), Decimal("0"))
    net_position_value = sum(position_values.values(), Decimal("0"))

    if nav:
        gross_exposure = gross_position_value / nav
        net_exposure = net_position_value / nav
        position_weights = {
            symbol: abs(value) / nav
            for symbol, value in position_values.items()
        }
    else:
        gross_exposure = Decimal("0")
        net_exposure = Decimal("0")
        position_weights = dict.fromkeys(position_values, Decimal("0"))

    max_position_symbol = max(position_weights, key=lambda symbol: position_weights[symbol]) if position_weights else None
    max_position_weight = position_weights[max_position_symbol] if max_position_symbol is not None else Decimal("0")

    alerts: list[PortfolioRiskAlert] = []
    if gross_exposure > max_gross_exposure:
        alerts.append(
            {
                "severity": "red",
                "action": "risk_officer.reduce_exposure",
                "metric": "gross_exposure",
                "value": gross_exposure,
                "threshold": max_gross_exposure,
            }
        )

    if max_position_weight > max_single_position_weight and max_position_symbol is not None:
        alerts.append(
            {
                "severity": "red",
                "action": "risk_officer.review_concentration",
                "metric": "single_position_weight",
                "symbol": max_position_symbol,
                "value": max_position_weight,
                "threshold": max_single_position_weight,
            }
        )

    return {
        "status": "red" if alerts else "ok",
        "metrics": {
            "nav": nav,
            "gross_exposure": gross_exposure,
            "net_exposure": net_exposure,
            "max_position_weight": max_position_weight,
            "max_position_symbol": max_position_symbol,
        },
        "alerts": alerts,
    }


def optimize_risk_constrained_weights(
    *,
    scores: dict[str, float],
    covariance: Sequence[Sequence[float]],
    symbols: list[str],
    industries: dict[str, str],
    max_position_weight: float,
    max_industry_weight: float,
    max_variance: float,
    risk_aversion: float = 1.0,
) -> dict[str, float]:
    if not symbols:
        raise ValueError("symbols is required")
    if set(symbols) - set(scores):
        raise ValueError("scores missing symbols")
    if max_position_weight <= 0 or max_industry_weight <= 0 or max_variance <= 0:
        raise ValueError("risk limits must be positive")

    import cvxpy as cp
    import numpy as np

    score_vector = np.array([float(scores[symbol]) for symbol in symbols], dtype=float)
    covariance_matrix = np.array(covariance, dtype=float)
    if covariance_matrix.shape != (len(symbols), len(symbols)):
        raise ValueError("covariance shape must match symbols")

    weights = cp.Variable(len(symbols))
    risk = cp.quad_form(weights, covariance_matrix)
    constraints = [
        weights >= 0,
        cp.sum(weights) == 1,
        weights <= max_position_weight,
        risk <= max_variance,
    ]
    for industry in sorted(set(industries.get(symbol, "") for symbol in symbols)):
        if not industry:
            continue
        indices = [index for index, symbol in enumerate(symbols) if industries.get(symbol) == industry]
        constraints.append(cp.sum(weights[indices]) <= max_industry_weight)

    problem = cp.Problem(cp.Maximize(score_vector @ weights - risk_aversion * risk), constraints)
    problem.solve()
    if problem.status not in {"optimal", "optimal_inaccurate"} or weights.value is None:
        raise ValueError("portfolio optimization failed")
    raw = [max(0.0, float(value)) for value in weights.value]
    total = sum(raw)
    if total <= 0:
        raise ValueError("portfolio optimization produced zero weights")
    return {symbol: raw[index] / total for index, symbol in enumerate(symbols)}
