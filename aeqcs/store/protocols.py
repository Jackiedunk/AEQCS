"""Storage protocols consumed by the deterministic core service."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

import pandas as pd


class CoreStore(Protocol):
    def load_daily(self) -> pd.DataFrame:
        ...

    def load_financials(self) -> pd.DataFrame:
        ...

    def get_market_data(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of_date: date | None = None,
    ) -> list[dict[str, Any]]:
        ...

    def get_financials(self, symbol: str, period: str, as_of_date: date | None = None) -> dict[str, Any]:
        ...

    def submit_proposal(self, proposal: Any) -> int:
        ...

    def get_proposal_status(self, proposal_id: int) -> dict[str, Any]:
        ...

    def review_proposal(self, review: Any) -> dict[str, Any]:
        ...

    def save_backtest_result(self, report: Any) -> str:
        ...

    def get_backtest_result(self, backtest_result_id: str) -> dict[str, Any]:
        ...

    def save_factor_values(self, values: list[dict[str, Any]]) -> int:
        ...

    def get_factor_values(
        self,
        factor_ids: list[str],
        start_date: date,
        end_date: date,
        as_of_date: date,
    ) -> list[dict[str, Any]]:
        ...

    def save_uploaded_doc(self, document: Any, chunks: list[Any]) -> dict[str, Any]:
        ...

    def get_uploaded_doc(self, sha256: str) -> dict[str, Any]:
        ...


class AsyncCoreStore(Protocol):
    async def load_daily(self) -> pd.DataFrame:
        ...

    async def load_financials(self) -> pd.DataFrame:
        ...

    async def get_market_data(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of_date: date | None = None,
    ) -> list[dict[str, Any]]:
        ...

    async def get_financials(
        self,
        symbol: str,
        period: str,
        as_of_date: date | None = None,
    ) -> dict[str, Any]:
        ...

    async def submit_proposal(self, proposal: Any) -> int:
        ...

    async def get_proposal_status(self, proposal_id: int) -> dict[str, Any]:
        ...

    async def review_proposal(self, review: Any) -> dict[str, Any]:
        ...

    async def save_backtest_result(self, report: Any) -> str:
        ...

    async def get_backtest_result(self, backtest_result_id: str) -> dict[str, Any]:
        ...

    async def save_factor_values(self, values: list[dict[str, Any]]) -> int:
        ...

    async def get_factor_values(
        self,
        factor_ids: list[str],
        start_date: date,
        end_date: date,
        as_of_date: date,
    ) -> list[dict[str, Any]]:
        ...

    async def save_uploaded_doc(self, document: Any, chunks: list[Any]) -> dict[str, Any]:
        ...

    async def get_uploaded_doc(self, sha256: str) -> dict[str, Any]:
        ...
