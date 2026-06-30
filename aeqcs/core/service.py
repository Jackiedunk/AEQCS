"""Application service behind MCP tools and local commands."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from aeqcs.core.exceptions import DataSourceError
from aeqcs.core.versioning import assert_not_after, require_as_of, stable_hash
from aeqcs.factor.compute.technical import compute_panel_momentum
from aeqcs.gate.proposals import Proposal, ProposalReview, ProposalStatus
from aeqcs.gate.validator import validate_structure
from aeqcs.ingest.document_parser import (
    chunk_text,
    decode_upload,
    parse_text_file,
    parse_text_upload,
    safe_upload_filename,
    sha256_bytes,
)
from aeqcs.ingest.extractor import extract_proposals
from aeqcs.store.protocols import AsyncCoreStore, CoreStore
from aeqcs.strategy.backtest.execution import ExecutionConfig
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

    def load_inbox(self, filename: str, content_base64: str, doc_type: str = "note") -> dict[str, Any]:
        safe_filename = safe_upload_filename(filename)
        content = decode_upload(content_base64)
        inbox = self.store.root / "inbox" if hasattr(self.store, "root") else None
        if inbox is None:
            raise ValueError("load_inbox requires a file-backed store")
        inbox.mkdir(parents=True, exist_ok=True)
        target = inbox / safe_filename
        target.write_bytes(content)
        document = parse_text_file(target, doc_type=doc_type)
        if document.sha256 != sha256_bytes(content):
            raise ValueError("document hash mismatch after write")
        chunks = chunk_text(document.sha256, document.text)
        saved = self.store.save_uploaded_doc(document, chunks)
        proposal_ids = []
        for proposal in extract_proposals(document.text, source=f"upload:{safe_filename}"):
            proposal_ids.append(
                self.submit_proposal(
                    proposal["kind"],
                    proposal["payload"],
                    proposal["source"],
                    proposal["confidence"],
                )
            )
        return {**saved, "proposal_ids": proposal_ids}

    def get_uploaded_doc(self, sha256: str) -> dict[str, Any]:
        return self.store.get_uploaded_doc(sha256)

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
            outputs.extend(
                self._factor_frame_to_records(
                    compute_panel_momentum(frame, window=20),
                    "momentum_20d",
                    "momentum_20d",
                    as_of_date,
                )
            )
        if "momentum_1d" in factor_ids:
            outputs.extend(
                self._factor_frame_to_records(
                    compute_panel_momentum(frame, window=1),
                    "momentum_1d",
                    "momentum_1d",
                    as_of_date,
                )
            )
        self.store.save_factor_values(outputs)
        return outputs

    def _factor_frame_to_records(
        self,
        frame,
        factor_id: str,
        value_column: str,
        as_of_date: date,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        calc_timestamp = datetime.combine(as_of_date, datetime.min.time())
        for row in frame.dropna(subset=[value_column]).to_dict("records"):
            records.append(
                {
                    "symbol": row["symbol"],
                    "date": row["date"],
                    "factor_id": factor_id,
                    "version": 1,
                    "value": row[value_column],
                    "calc_timestamp": calc_timestamp,
                }
            )
        return records

    def get_factor_values(
        self,
        factor_ids: list[str],
        start_date: date,
        end_date: date,
        as_of_date: date,
    ) -> list[dict[str, Any]]:
        require_as_of(as_of_date)
        assert_not_after(end_date, as_of_date)
        return self.store.get_factor_values(factor_ids, start_date, end_date, as_of_date)

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
            ExecutionConfig(
                fee_rate=Decimal(str(parameters.get("fee_rate", "0"))),
                min_fee=Decimal(str(parameters.get("min_fee", "0"))),
                slippage_bps=Decimal(str(parameters.get("slippage_bps", "0"))),
                lot_size=int(parameters.get("lot_size", 100)),
            ),
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


class AsyncCoreService:
    def __init__(self, store: AsyncCoreStore) -> None:
        self.store = store

    async def load_inbox(self, filename: str, content_base64: str, doc_type: str = "note") -> dict[str, Any]:
        content = decode_upload(content_base64)
        document = parse_text_upload(filename, content, doc_type=doc_type)
        chunks = chunk_text(document.sha256, document.text)
        saved = await self.store.save_uploaded_doc(document, chunks)
        proposal_ids = []
        for proposal in extract_proposals(document.text, source=f"upload:{document.filename}"):
            proposal_ids.append(
                await self.submit_proposal(
                    proposal["kind"],
                    proposal["payload"],
                    proposal["source"],
                    proposal["confidence"],
                )
            )
        return {**saved, "proposal_ids": proposal_ids}

    async def get_uploaded_doc(self, sha256: str) -> dict[str, Any]:
        return await self.store.get_uploaded_doc(sha256)

    async def submit_proposal(
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
        return await self.store.submit_proposal(proposal)
