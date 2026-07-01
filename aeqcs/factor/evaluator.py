"""Factor evaluation helpers."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, cast

import pandas as pd

from aeqcs.core.versioning import (
    assert_not_after,
    require_as_of,
    require_date_value,
    require_finite_number,
    require_non_empty_text,
)


def information_coefficient(factor: pd.Series, forward_return: pd.Series) -> float:
    joined = pd.concat([factor.rename("factor"), forward_return.rename("ret")], axis=1).dropna()
    if joined.empty:
        return float("nan")
    return float(joined["factor"].corr(joined["ret"], method="spearman"))


def qlib_icir_report(
    aligned_frame: pd.DataFrame,
    *,
    as_of_date: date | None,
    factor_column: str = "factor",
    forward_return_column: str = "forward_return",
) -> dict[str, Any]:
    checked_as_of = require_as_of(as_of_date)
    required = {"date", "symbol", factor_column, forward_return_column}
    missing = required - set(aligned_frame.columns)
    if missing:
        raise ValueError(f"IC/IR frame missing columns: {sorted(missing)}")
    if aligned_frame.empty:
        raise ValueError("IC/IR frame is empty")
    frame = aligned_frame.copy()
    frame["date"] = frame["date"].map(lambda value: require_date_value(value, "date"))
    frame["symbol"] = frame["symbol"].map(lambda value: require_non_empty_text(value, "symbol"))
    frame[factor_column] = frame[factor_column].map(
        lambda value: require_finite_number(value, factor_column)
    )
    frame[forward_return_column] = frame[forward_return_column].map(
        lambda value: require_finite_number(value, forward_return_column)
    )
    if frame.duplicated(subset=["date", "symbol"]).any():
        raise ValueError("IC/IR frame has duplicate date/symbol rows")
    latest_date = cast(date, frame["date"].max())
    assert_not_after(latest_date, checked_as_of)
    ic_values = []
    for _, group in frame.groupby("date", sort=True):
        ic_values.append(information_coefficient(group[factor_column], group[forward_return_column]))
    ic_by_date = pd.Series(ic_values).dropna()
    if ic_by_date.empty:
        raise ValueError("IC/IR frame has no valid aligned observations")
    ic = float(ic_by_date.mean())
    std = float(ic_by_date.std(ddof=1)) if len(ic_by_date) > 1 else 0.0
    icir = ic / std if std > 0 else 0.0
    return {
        "as_of_date": checked_as_of.isoformat(),
        "metrics": {
            "ic": ic,
            "icir": icir,
            "observations": float(len(frame.dropna(subset=[factor_column, forward_return_column]))),
            "dates": float(len(ic_by_date)),
        },
    }


def qlib_risk_analysis(nav_series: pd.Series):
    try:
        from qlib.contrib.evaluate import risk_analysis  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install the qlib extra to use Qlib risk analysis") from exc
    return risk_analysis(nav_series)


def qlib_portfolio_optimizer(alpha: pd.Series, risk_matrix: pd.DataFrame | None = None) -> pd.Series:
    del risk_matrix
    positive_alpha = alpha.dropna().astype(float)
    positive_alpha = positive_alpha[positive_alpha > 0].sort_index()
    if positive_alpha.empty:
        raise ValueError("optimization alpha has no positive scores")
    total = float(positive_alpha.sum())
    if total <= 0:
        raise ValueError("optimization alpha has no positive scores")
    return positive_alpha / total


def qlib_portfolio_optimization_report(
    alpha: pd.Series,
    *,
    as_of_date: date | None,
    risk_matrix: pd.DataFrame | None = None,
    optimizer_fn: Callable[[pd.Series, pd.DataFrame | None], pd.Series] = qlib_portfolio_optimizer,
) -> dict[str, Any]:
    checked_as_of = require_as_of(as_of_date)
    if alpha.empty:
        raise ValueError("optimization alpha is empty")
    if not isinstance(alpha.index, pd.MultiIndex) or set(alpha.index.names) != {"date", "symbol"}:
        raise ValueError("optimization alpha must use a MultiIndex named date and symbol")
    alpha_frame = alpha.rename("alpha").reset_index()
    alpha_frame["date"] = alpha_frame["date"].map(lambda value: require_date_value(value, "date"))
    alpha_frame["symbol"] = alpha_frame["symbol"].map(
        lambda value: require_non_empty_text(value, "symbol")
    )
    alpha_frame["alpha"] = alpha_frame["alpha"].map(lambda value: require_finite_number(value, "alpha"))
    if alpha_frame.duplicated(subset=["date", "symbol"]).any():
        raise ValueError("optimization alpha has duplicate date/symbol rows")
    latest_date = cast(date, alpha_frame["date"].max())
    assert_not_after(latest_date, checked_as_of)
    scoped = alpha_frame[alpha_frame["date"] == checked_as_of].dropna(subset=["alpha"])
    if scoped.empty:
        raise ValueError("optimization alpha has no rows for as_of_date")
    alpha_slice = pd.Series(
        scoped["alpha"].astype(float).to_list(),
        index=scoped["symbol"].astype(str).to_list(),
        name="alpha",
    ).sort_index()
    weights = _finite_portfolio_weights(
        optimizer_fn(alpha_slice, risk_matrix),
        allowed_symbols=set(alpha_slice.index),
    )
    weights = weights.map(lambda value: round(value, 12))
    gross_exposure = round(float(weights.abs().sum()), 12)
    if gross_exposure <= 0:
        raise ValueError("optimization weights gross exposure is zero")
    net_exposure = round(float(weights.sum()), 12)
    return {
        "as_of_date": checked_as_of.isoformat(),
        "weights": {str(symbol): float(weight) for symbol, weight in weights.items()},
        "metrics": {
            "gross_exposure": gross_exposure,
            "net_exposure": net_exposure,
            "positions": float(len(weights)),
        },
    }


def _risk_metrics_to_dict(result: Any) -> dict[str, float]:
    if isinstance(result, pd.Series):
        return _finite_risk_metrics(_series_to_metric_dict(result.dropna()))
    if isinstance(result, pd.DataFrame):
        if len(result.columns) == 1:
            series = result.iloc[:, 0]
            return _finite_risk_metrics(_series_to_metric_dict(series.dropna()))
        if len(result.index) == 1:
            row = result.iloc[0]
            return _finite_risk_metrics(_series_to_metric_dict(row.dropna()))
    if isinstance(result, dict):
        return _finite_risk_metrics({key: value for key, value in result.items() if pd.notna(value)})
    raise ValueError(f"unsupported Qlib risk_analysis output type: {type(result).__name__}")


def _series_to_metric_dict(series: pd.Series) -> dict[Any, Any]:
    metrics = series.index.to_list()
    duplicate_metrics = sorted({str(metric) for metric in metrics if metrics.count(metric) > 1})
    if duplicate_metrics:
        raise ValueError(f"duplicate risk metric names: {duplicate_metrics}")
    return series.to_dict()


def _finite_portfolio_weights(weights: pd.Series, *, allowed_symbols: set[str]) -> pd.Series:
    clean = weights.dropna()
    if clean.empty:
        raise ValueError("optimization weights are empty")
    symbols = [require_non_empty_text(symbol, "symbol") for symbol in clean.index]
    duplicate_symbols = sorted({symbol for symbol in symbols if symbols.count(symbol) > 1})
    if duplicate_symbols:
        raise ValueError(f"optimization weights include duplicate symbols: {duplicate_symbols}")
    unknown_symbols = sorted(set(symbols) - allowed_symbols)
    if unknown_symbols:
        raise ValueError(f"optimization weights include unknown symbols: {unknown_symbols}")
    return pd.Series(
        [
            float(require_finite_number(value, "weight"))
            for value in clean.to_list()
        ],
        index=symbols,
        name=weights.name,
    ).sort_index()


def _finite_risk_metrics(metrics: dict[Any, Any]) -> dict[str, float]:
    if not metrics:
        raise ValueError("risk metrics are empty")
    clean: dict[str, float] = {}
    for key, value in metrics.items():
        metric_name = _risk_metric_name(key)
        clean[metric_name] = float(require_finite_number(value, metric_name))
    return clean


def _risk_metric_name(key: Any) -> str:
    return require_non_empty_text(key, "risk metric name")


def qlib_risk_report(
    nav_series: pd.Series,
    *,
    as_of_date: date | None,
    risk_analysis_fn: Callable[[pd.Series], Any] = qlib_risk_analysis,
) -> dict[str, Any]:
    checked_as_of = require_as_of(as_of_date)
    if nav_series.empty:
        raise ValueError("NAV series is empty")
    clean_dates = [require_date_value(value, "date") for value in nav_series.index]
    clean_values = [require_finite_number(value, "nav") for value in nav_series.to_list()]
    nav = pd.Series(
        clean_values,
        index=pd.to_datetime(clean_dates),
        name=nav_series.name,
    )
    latest_date = cast(date, nav.index.date.max())
    assert_not_after(latest_date, checked_as_of)
    result = risk_analysis_fn(nav)
    return {
        "as_of_date": checked_as_of.isoformat(),
        "metrics": _risk_metrics_to_dict(result),
    }
