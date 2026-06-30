"""Factor evaluation helpers."""

from __future__ import annotations

import pandas as pd


def information_coefficient(factor: pd.Series, forward_return: pd.Series) -> float:
    joined = pd.concat([factor.rename("factor"), forward_return.rename("ret")], axis=1).dropna()
    if joined.empty:
        return float("nan")
    return float(joined["factor"].corr(joined["ret"], method="spearman"))


def qlib_risk_analysis(nav_series: pd.Series):
    try:
        from qlib.contrib.evaluate import risk_analysis  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install the qlib extra to use Qlib risk analysis") from exc
    return risk_analysis(nav_series)
