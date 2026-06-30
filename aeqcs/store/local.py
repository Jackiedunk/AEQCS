"""Local file-backed store for development and deterministic tests."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from aeqcs.core.versioning import assert_not_after, require_as_of
from aeqcs.data.etl.financial_data import normalize_financial_frame, pit_slice
from aeqcs.data.etl.market_data import normalize_daily_frame
from aeqcs.gate.proposals import ProposalReview
from aeqcs.gate.validator import assert_transition
from aeqcs.ingest.document_parser import DocumentChunk, ParsedDocument
from aeqcs.strategy.backtest.engine import BacktestReport


class LocalStore:
    """Small CSV-backed store used before PostgreSQL is available."""

    def __init__(self, root: str | Path = "data/local") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.daily_path = self.root / "stock_daily_origin.csv"
        self.financial_path = self.root / "financial_indicators.csv"
        self.proposals_path = self.root / "proposals.csv"
        self.backtest_results_path = self.root / "backtest_results.csv"
        self.factor_values_path = self.root / "factor_values.csv"
        self.docs_path = self.root / "uploaded_docs.csv"
        self.chunks_path = self.root / "doc_chunks.csv"

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
        if end_date is not None:
            assert_not_after(end_date, as_of_date)
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

    def review_proposal(self, review: ProposalReview) -> dict[str, Any]:
        if not self.proposals_path.exists():
            return {}
        frame = pd.read_csv(self.proposals_path)
        mask = frame["proposal_id"] == review.proposal_id
        if not mask.any():
            return {}
        current = str(frame.loc[mask, "status"].iloc[-1])
        assert_transition(current, review.status)
        frame.loc[mask, "status"] = review.status.value
        frame.loc[mask, "reviewed_by"] = review.reviewed_by
        frame.loc[mask, "review_reason"] = review.reason
        if review.backtest_result is not None:
            frame.loc[mask, "backtest_result"] = json.dumps(
                review.backtest_result,
                ensure_ascii=False,
                default=str,
            )
        frame.to_csv(self.proposals_path, index=False)
        return self.get_proposal_status(review.proposal_id)

    def save_backtest_result(self, report: BacktestReport) -> str:
        payload = {
            "backtest_result_id": report.backtest_result_id,
            "strategy_name": report.strategy_name,
            "start_date": report.start_date.isoformat(),
            "end_date": report.end_date.isoformat(),
            "as_of_date": report.as_of_date.isoformat(),
            "parameters": json.dumps(report.parameters, ensure_ascii=False, default=str),
            "fills": json.dumps([asdict(fill) for fill in report.fills], ensure_ascii=False, default=str),
            "nav": json.dumps(report.nav, ensure_ascii=False, default=str),
        }
        existing = (
            pd.read_csv(self.backtest_results_path, dtype={"backtest_result_id": str})
            if self.backtest_results_path.exists()
            else pd.DataFrame()
        )
        merged = pd.concat([existing, pd.DataFrame([payload])], ignore_index=True)
        merged = merged.drop_duplicates(["backtest_result_id"], keep="last")
        merged.to_csv(self.backtest_results_path, index=False)
        return report.backtest_result_id

    def get_backtest_result(self, backtest_result_id: str) -> dict[str, Any]:
        if not self.backtest_results_path.exists():
            return {}
        frame = pd.read_csv(self.backtest_results_path, dtype={"backtest_result_id": str})
        subset = frame[frame["backtest_result_id"] == backtest_result_id]
        if subset.empty:
            return {}
        row = subset.iloc[-1].to_dict()
        return {
            "backtest_result_id": row["backtest_result_id"],
            "strategy_name": row["strategy_name"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "as_of_date": row["as_of_date"],
            "parameters": json.loads(row["parameters"]),
            "fills": json.loads(row["fills"]),
            "nav": json.loads(row["nav"]),
        }

    def save_factor_values(self, values: list[dict[str, Any]]) -> int:
        if not values:
            return 0
        incoming = pd.DataFrame(values)
        incoming["symbol"] = incoming["symbol"].astype(str)
        incoming["date"] = pd.to_datetime(incoming["date"]).dt.date
        incoming["factor_id"] = incoming["factor_id"].astype(str)
        incoming["version"] = incoming["version"].astype(int)
        incoming["calc_timestamp"] = pd.to_datetime(incoming["calc_timestamp"]).astype(str)
        existing = (
            pd.read_csv(self.factor_values_path, dtype={"symbol": str, "factor_id": str})
            if self.factor_values_path.exists()
            else pd.DataFrame()
        )
        merged = pd.concat([existing, incoming], ignore_index=True)
        merged = merged.drop_duplicates(["symbol", "date", "factor_id", "version"], keep="last")
        merged.to_csv(self.factor_values_path, index=False)
        return len(incoming)

    def get_factor_values(
        self,
        factor_ids: list[str],
        start_date: date,
        end_date: date,
        as_of_date: date,
    ) -> list[dict[str, Any]]:
        require_as_of(as_of_date)
        assert_not_after(end_date, as_of_date)
        if not self.factor_values_path.exists():
            return []
        frame = pd.read_csv(self.factor_values_path, dtype={"symbol": str, "factor_id": str})
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        frame["calc_timestamp"] = pd.to_datetime(frame["calc_timestamp"])
        subset = frame[
            frame["factor_id"].isin(factor_ids)
            & (frame["date"] >= start_date)
            & (frame["date"] <= end_date)
            & (frame["date"] <= as_of_date)
        ]
        subset = subset.sort_values(["factor_id", "symbol", "date"]).copy()
        subset["date"] = subset["date"].map(lambda value: value.isoformat())
        subset["calc_timestamp"] = subset["calc_timestamp"].map(lambda value: value.isoformat())
        return subset.to_dict("records")

    def save_uploaded_doc(self, document: ParsedDocument, chunks: list[DocumentChunk]) -> dict[str, Any]:
        docs = (
            pd.read_csv(self.docs_path, dtype={"sha256": str})
            if self.docs_path.exists()
            else pd.DataFrame()
        )
        existing = docs[docs["sha256"] == document.sha256] if not docs.empty else pd.DataFrame()
        if existing.empty:
            doc_id = int(docs["doc_id"].max() + 1) if not docs.empty else 1
            row = {
                "doc_id": doc_id,
                "uploaded_ts": document.uploaded_ts.isoformat(),
                "filename": document.filename,
                "doc_type": document.doc_type,
                "path": document.path,
                "sha256": document.sha256,
                "status": "parsed",
                "meta": "{}",
            }
            docs = pd.concat([docs, pd.DataFrame([row])], ignore_index=True)
            docs.to_csv(self.docs_path, index=False)
        else:
            doc_id = int(existing.iloc[-1]["doc_id"])

        chunk_rows = [
            {"doc_id": doc_id, "doc_sha256": chunk.doc_sha256, "seq": chunk.seq, "text": chunk.text}
            for chunk in chunks
        ]
        existing_chunks = (
            pd.read_csv(self.chunks_path, dtype={"doc_sha256": str})
            if self.chunks_path.exists()
            else pd.DataFrame()
        )
        if chunk_rows:
            merged_chunks = pd.concat([existing_chunks, pd.DataFrame(chunk_rows)], ignore_index=True)
            merged_chunks = merged_chunks.drop_duplicates(["doc_sha256", "seq"], keep="last")
            merged_chunks.to_csv(self.chunks_path, index=False)
        elif not self.chunks_path.exists():
            pd.DataFrame(columns=["doc_id", "doc_sha256", "seq", "text"]).to_csv(self.chunks_path, index=False)

        return {"doc_id": doc_id, "sha256": document.sha256, "chunks": len(chunks)}

    def get_uploaded_doc(self, sha256: str) -> dict[str, Any]:
        if not self.docs_path.exists():
            return {}
        docs = pd.read_csv(self.docs_path, dtype={"sha256": str})
        subset = docs[docs["sha256"] == sha256]
        if subset.empty:
            return {}
        row = subset.iloc[-1].to_dict()
        chunks = []
        if self.chunks_path.exists():
            chunk_frame = pd.read_csv(self.chunks_path, dtype={"doc_sha256": str})
            chunks = (
                chunk_frame[chunk_frame["doc_sha256"] == sha256]
                .sort_values("seq")[["seq", "text"]]
                .to_dict("records")
            )
        row["chunks"] = chunks
        return row
