"""Local file-backed store for development and deterministic tests."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from aeqcs.core.versioning import require_as_of
from aeqcs.data.etl.financial_data import normalize_financial_frame, pit_slice
from aeqcs.data.etl.market_data import normalize_daily_frame


class LocalStore:
    """Small CSV-backed store used before PostgreSQL is available."""

    def __init__(self, root: str | Path = "data/local") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.daily_path = self.root / "stock_daily_origin.csv"
        self.financial_path = self.root / "financial_indicators.csv"
        self.proposals_path = self.root / "proposals.csv"

    def load_daily(self) -> pd.DataFrame:
        if not self.daily_path.exists():
            return pd.DataFrame(
                columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"]
            )
        return normalize_daily_frame(pd.read_csv(self.daily_path, dtype={"symbol": str}))

    def save_daily(self, frame: pd.DataFrame) -> None:
        normalize_daily_frame(frame).to_csv(self.daily_path, index=False)

    def load_financials(self) -> pd.DataFrame:
        if not self.financial_path.exists():
            return pd.DataFrame(
                columns=[
                    "symbol",
                    "period",
                    "ann_date",
                    "vintage",
                    "roe",
                    "eps",
                    "bps",
                    "revenue_yoy",
                    "profit_yoy",
                    "debt_ratio",
                    "current_ratio",
                ]
            )
        return normalize_financial_frame(pd.read_csv(self.financial_path, dtype={"symbol": str, "period": str}))

    def save_financials(self, frame: pd.DataFrame) -> None:
        normalize_financial_frame(frame).to_csv(self.financial_path, index=False)

    def get_market_data(
        self,
        symbol: str,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of_date: date | None = None,
    ) -> list[dict[str, Any]]:
        require_as_of(as_of_date)
        frame = self.load_daily()
        if frame.empty:
            return []
        subset = frame[(frame["symbol"] == symbol) & (frame["date"] <= as_of_date)]
        if start_date is not None:
            subset = subset[subset["date"] >= start_date]
        if end_date is not None:
            subset = subset[subset["date"] <= end_date]
        return subset.sort_values("date").to_dict("records")

    def get_financials(self, symbol: str, period: str, as_of_date: date | None = None) -> dict[str, Any]:
        return pit_slice(self.load_financials(), symbol, period, as_of_date)

    def submit_proposal(self, proposal: Any) -> int:
        payload = asdict(proposal) if hasattr(proposal, "__dataclass_fields__") else dict(proposal)
        existing = pd.read_csv(self.proposals_path) if self.proposals_path.exists() else pd.DataFrame()
        proposal_id = int(existing["proposal_id"].max() + 1) if not existing.empty else 1
        row = {"proposal_id": proposal_id, "status": "pending", **payload}
        pd.concat([existing, pd.DataFrame([row])], ignore_index=True).to_csv(
            self.proposals_path, index=False
        )
        return proposal_id

    def get_proposal_status(self, proposal_id: int) -> dict[str, Any]:
        if not self.proposals_path.exists():
            return {}
        frame = pd.read_csv(self.proposals_path)
        subset = frame[frame["proposal_id"] == proposal_id]
        if subset.empty:
            return {}
        row = subset.iloc[-1].to_dict()
        return {"status": row.get("status", ""), "result": row}
