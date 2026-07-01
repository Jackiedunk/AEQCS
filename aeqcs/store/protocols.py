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

    def get_index_constituents(
        self,
        index_code: str,
        as_of_date: date | None = None,
    ) -> list[dict[str, Any]]:
        ...

    def get_active_stock_universe(self, as_of_date: date | None = None) -> list[dict[str, Any]]:
        ...

    def submit_proposal(self, proposal: Any) -> int:
        ...

    def get_proposal_status(self, proposal_id: int) -> dict[str, Any]:
        ...

    def review_proposal(self, review: Any) -> dict[str, Any]:
        ...

    def approve_proposal(self, proposal_id: int, approver_id: str, decision: str) -> dict[str, Any]:
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

    def save_universe_node(self, node: dict[str, Any]) -> str:
        ...

    def save_universe_edge(self, edge: dict[str, Any]) -> int:
        ...

    def verify_universe_edge(self, edge_id: int, verified_by: str, as_of_date: date) -> dict[str, Any]:
        ...

    def retire_universe_edge(self, edge_id: int, retired_by: str, as_of_date: date) -> dict[str, Any]:
        ...

    def get_universe_children_as_of(self, parent_id: str, as_of_date: date) -> list[str]:
        ...

    def search_semantic_nodes(
        self,
        query: str,
        as_of_date: date,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
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

    async def get_index_constituents(
        self,
        index_code: str,
        as_of_date: date | None = None,
    ) -> list[dict[str, Any]]:
        ...

    async def get_active_stock_universe(self, as_of_date: date | None = None) -> list[dict[str, Any]]:
        ...

    async def submit_proposal(self, proposal: Any) -> int:
        ...

    async def get_proposal_status(self, proposal_id: int) -> dict[str, Any]:
        ...

    async def review_proposal(self, review: Any) -> dict[str, Any]:
        ...

    async def approve_proposal(self, proposal_id: int, approver_id: str, decision: str) -> dict[str, Any]:
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

    async def save_universe_node(self, node: dict[str, Any]) -> str:
        ...

    async def save_universe_edge(self, edge: dict[str, Any]) -> int:
        ...

    async def verify_universe_edge(self, edge_id: int, verified_by: str, as_of_date: date) -> dict[str, Any]:
        ...

    async def retire_universe_edge(self, edge_id: int, retired_by: str, as_of_date: date) -> dict[str, Any]:
        ...

    async def get_universe_children_as_of(self, parent_id: str, as_of_date: date) -> list[str]:
        ...

    async def search_semantic_nodes(
        self,
        query: str,
        as_of_date: date,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        ...

    async def save_backtest_task(self, task: dict[str, Any]) -> str:
        ...

    async def get_backtest_task(self, task_id: str) -> dict[str, Any]:
        ...
