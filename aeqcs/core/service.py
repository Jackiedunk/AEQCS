"""Application service behind MCP tools and local commands."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from aeqcs.core.exceptions import DataSourceError
from aeqcs.core.versioning import assert_not_after, require_as_of, stable_hash
from aeqcs.factor.compute.technical import compute_panel_momentum
from aeqcs.gate.proposals import Proposal, ProposalReview, ProposalStatus
from aeqcs.gate.validator import validate_structure
from aeqcs.store.protocols import CoreStore
from aeqcs.strategy.backtest.engine import BacktestReport, run_daily_backtest
from aeqcs.strategy.base import BuyAndHoldStrategy


class CoreService:
    def __init__(self, store: CoreStore) -> None:
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
        assert_not_after(end_date, as_of_date)
        supported = {"momentum_20d", "momentum_1d"}
        unknown = set(factor_ids) - supported
        if unknown:
            raise ValueError(f"unsupported factor ids: {sorted(unknown)}")
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
        assert_not_after(end_date, as_of_date)
        if strategy_name != "buy_and_hold":
            raise ValueError(f"unsupported strategy: {strategy_name}")
        symbol = str(parameters["symbol"])
        rows = self.store.get_market_data(symbol, start_date, end_date, as_of_date)
        if not rows:
            raise DataSourceError(f"no market data for {symbol} between {start_date} and {end_date}")
        result = run_daily_backtest(
            rows,
            BuyAndHoldStrategy(symbol, float(parameters.get("target_weight", 1.0))),
            Decimal(str(parameters.get("initial_cash", "1000000"))),
        )
        report_id = stable_hash(
            {
                "strategy_name": strategy_name,
                "start_date": start_date,
                "end_date": end_date,
                "as_of_date": as_of_date,
                "parameters": parameters,
            }
        )
        report = BacktestReport(
            backtest_result_id=report_id,
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            as_of_date=as_of_date,
            parameters=parameters,
            fills=result.fills,
            nav=result.nav,
        )
        return {"backtest_result_id": self.store.save_backtest_result(report)}

    def get_backtest_result(self, backtest_result_id: str) -> dict[str, Any]:
        return self.store.get_backtest_result(backtest_result_id)

    def submit_proposal(
        self,
        kind: str,
        payload: dict[str, Any],
        source: str,
        confidence: float,
        snapshot_id: int | None = None,
    ) -> int:
        errors = validate_structure(kind, payload)
        if errors:
            raise ValueError("; ".join(errors))
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

    def review_proposal(
        self,
        proposal_id: int,
        status: str,
        reviewed_by: str,
        reason: str = "",
        backtest_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        review = ProposalReview(
            proposal_id=proposal_id,
            status=ProposalStatus(status),
            reviewed_by=reviewed_by,
            reason=reason,
            backtest_result=backtest_result,
        )
        return self.store.review_proposal(review)
