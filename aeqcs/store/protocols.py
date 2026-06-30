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
