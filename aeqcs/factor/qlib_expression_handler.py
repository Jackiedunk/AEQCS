"""Qlib expression engine wrapper."""

from __future__ import annotations

from typing import Any

import pandas as pd


class QlibFactorEngine:
    def __init__(self, data_handler: Any) -> None:
        self.handler = data_handler

    def compute_expression(
        self,
        expression_str: str,
        symbols: list[str],
        start_date: str,
        end_date: str,
    ) -> pd.Series:
        try:
            from qlib.data import D  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Install the qlib extra to use Qlib expressions") from exc

        return D.features(symbols, [expression_str], start_time=start_date, end_time=end_date).iloc[:, 0]
