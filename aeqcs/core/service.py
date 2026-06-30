"""Application service behind MCP tools and local commands."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any

from aeqcs.core.versioning import require_as_of
from aeqcs.factor.compute.technical import compute_panel_momentum
from aeqcs.gate.proposals import Proposal
from aeqcs.store.local import LocalStore
from aeqcs.strategy.backtest.engine import run_daily_backtest
from aeqcs.strategy.base import BuyAndHoldStrategy


class CoreService:
    def __init__(self, store: LocalStore) -> None:
        self.store = store

    def get_market_data(self, symbol: str, as_of_date: date) -> dict[str, Any]:
        rows = self.store.get_market_data(symbol, as_of_date=as_of_date)
        return rows[-1] if rows else {}

    def get_financials(self, symbol: str, period: str, as_of_date: date) -> dict[str, Any]:
        return self.store.get_financials(symbol, period, as_of_date)

    def compute_factors(
        self,
        factor_ids: list[str],
        start_date: date,
        end_date: date,
        as_of_date: date,
    ) -> list[dict[str, Any]]:
        require_as_of(as_of_date)
        frame = self.store.load_daily()
        if frame.empty:
            return []
        frame = frame[(frame["date"] >= start_date) & (frame["date"] <= end_date)]
        frame = frame[frame["date"] <= as_of_date]
        outputs: list[dict[str, Any]] = []
        if "momentum_20d" in factor_ids:
            outputs.extend(compute_panel_momentum(frame, window=20).dropna().to_dict("records"))
        if "momentum_1d" in factor_ids:
            outputs.extend(compute_panel_momentum(frame, window=1).dropna().to_dict("records"))
        return outputs

    def run_backtest(
        self,
        strategy_name: str,
        start_date: date,
        end_date: date,
        parameters: dict[str, Any],
        as_of_date: date,
    ) -> dict[str, Any]:
        require_as_of(as_of_date)
        if strategy_name != "buy_and_hold":
            raise ValueError(f"unsupported strategy: {strategy_name}")
        symbol = str(parameters["symbol"])
        rows = self.store.get_market_data(symbol, start_date, end_date, as_of_date)
        result = run_daily_backtest(
            rows,
            BuyAndHoldStrategy(symbol, float(parameters.get("target_weight", 1.0))),
            Decimal(str(parameters.get("initial_cash", "1000000"))),
        )
        return {"fills": [asdict(fill) for fill in result.fills], "nav": result.nav}

    def submit_proposal(
        self,
        kind: str,
        payload: dict[str, Any],
        source: str,
        confidence: float,
        snapshot_id: int | None = None,
    ) -> int:
        proposal = Proposal(
            kind=kind,
            payload=payload,
            source=source,
            confidence=confidence,
            snapshot_id=snapshot_id,
        )
        return self.store.submit_proposal(proposal)

    def get_proposal_status(self, proposal_id: int) -> dict[str, Any]:
        return self.store.get_proposal_status(proposal_id)
