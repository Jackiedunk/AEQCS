"""Application service behind MCP tools and local commands."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from aeqcs.core.exceptions import DataSourceError, LookAheadViolation
from aeqcs.core.versioning import (
    assert_not_after,
    require_as_of,
    require_non_empty_text,
    require_valid_date_range,
    stable_hash,
)
from aeqcs.factor.compute.fundamental import (
    compute_bps_quarterly_values,
    compute_current_ratio_quarterly_values,
    compute_debt_ratio_quarterly_values,
    compute_debt_to_equity_quarterly_values,
    compute_equity_ratio_quarterly_values,
    compute_eps_quarterly_values,
    compute_gross_margin_quarterly_values,
    compute_margin_spread_quarterly_values,
    compute_net_margin_quarterly_values,
    compute_profit_yoy_quarterly_values,
    compute_quick_ratio_quarterly_values,
    compute_revenue_yoy_quarterly_values,
    compute_roe_quarterly_values,
)
from aeqcs.factor.pipeline import (
    DUCKDB_FACTOR_WINDOWS,
    DUCKDB_SUPPORTED_FACTORS,
    compute_duckdb_factor_values,
)
from aeqcs.factor.registry import FactorSpec
from aeqcs.gate.proposals import Proposal, ProposalKind, ProposalReview, ProposalStatus
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
from aeqcs.knowledge.universe_builder import UniverseBuilder
from aeqcs.runtime.intraday import load_cep_rules, scan_cep_events
from aeqcs.store.protocols import AsyncCoreStore, CoreStore
from aeqcs.strategy.backtest.execution import ExecutionConfig
from aeqcs.strategy.backtest.engine import BacktestReport, run_daily_backtest
from aeqcs.strategy.base import BuyAndHoldStrategy
from aeqcs.strategy.portfolio import Portfolio, scan_portfolio_risk as scan_portfolio_risk_report
from aeqcs.strategy.risk import scan_drawdown_risk as scan_drawdown_risk_report


FUNDAMENTAL_PIT_COMPUTERS = {
    "roe_quarterly": compute_roe_quarterly_values,
    "debt_ratio_quarterly": compute_debt_ratio_quarterly_values,
    "equity_ratio_quarterly": compute_equity_ratio_quarterly_values,
    "debt_to_equity_quarterly": compute_debt_to_equity_quarterly_values,
    "profit_yoy_quarterly": compute_profit_yoy_quarterly_values,
    "current_ratio_quarterly": compute_current_ratio_quarterly_values,
    "quick_ratio_quarterly": compute_quick_ratio_quarterly_values,
    "revenue_yoy_quarterly": compute_revenue_yoy_quarterly_values,
    "eps_quarterly": compute_eps_quarterly_values,
    "bps_quarterly": compute_bps_quarterly_values,
    "gross_margin_quarterly": compute_gross_margin_quarterly_values,
    "net_margin_quarterly": compute_net_margin_quarterly_values,
    "margin_spread_quarterly": compute_margin_spread_quarterly_values,
}
FUNDAMENTAL_PIT_FACTORS = set(FUNDAMENTAL_PIT_COMPUTERS)


def _decimal_parameter(parameters: dict[str, Any], name: str, default: str) -> Decimal:
    raw = parameters.get(name, default)
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"parameters.{name} must be a decimal") from exc
    if not value.is_finite():
        raise ValueError(f"parameters.{name} must be finite")
    return value


def _float_parameter(parameters: dict[str, Any], name: str, default: str) -> float:
    raw = parameters.get(name, default)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"parameters.{name} must be numeric") from exc
    if not math.isfinite(value):
        raise ValueError(f"parameters.{name} must be finite")
    return value


def _int_parameter(parameters: dict[str, Any], name: str, default: int) -> int:
    raw = parameters.get(name, default)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"parameters.{name} must be an integer") from exc


def validate_backtest_parameters(parameters: dict[str, Any]) -> tuple[str, float, Decimal, ExecutionConfig]:
    symbol = str(parameters.get("symbol", "")).strip()
    if not symbol:
        raise ValueError("parameters.symbol is required")

    target_weight = _float_parameter(parameters, "target_weight", "1.0")
    if target_weight < 0:
        raise ValueError("parameters.target_weight must be non-negative")

    initial_cash = _decimal_parameter(parameters, "initial_cash", "1000000")
    if initial_cash <= 0:
        raise ValueError("parameters.initial_cash must be positive")

    fee_rate = _decimal_parameter(parameters, "fee_rate", "0")
    min_fee = _decimal_parameter(parameters, "min_fee", "0")
    slippage_bps = _decimal_parameter(parameters, "slippage_bps", "0")
    if fee_rate < 0:
        raise ValueError("parameters.fee_rate must be non-negative")
    if min_fee < 0:
        raise ValueError("parameters.min_fee must be non-negative")
    if slippage_bps < 0:
        raise ValueError("parameters.slippage_bps must be non-negative")

    lot_size = _int_parameter(parameters, "lot_size", 100)
    if lot_size <= 0:
        raise ValueError("parameters.lot_size must be positive")

    return (
        symbol,
        target_weight,
        initial_cash,
        ExecutionConfig(
            fee_rate=fee_rate,
            min_fee=min_fee,
            slippage_bps=slippage_bps,
            lot_size=lot_size,
        ),
    )


def require_audit_identity(value: str, field: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{field} is required")


def require_approval_decision(value: str) -> str:
    decision = require_non_empty_text(value, "decision")
    if decision != "promote":
        raise ValueError(f"unsupported approval decision: {decision}")
    return decision


def require_positive_integer_id(value: int, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def require_optional_positive_integer_id(value: object, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def validate_factor_ids(factor_ids: object) -> list[str]:
    if not isinstance(factor_ids, list):
        raise ValueError("factor_ids must be a list of non-empty strings")
    if not factor_ids or any(not isinstance(factor_id, str) or not factor_id.strip() for factor_id in factor_ids):
        raise ValueError("factor_ids must be a list of non-empty strings")
    return factor_ids


def validate_record_list(rows: object, field: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{field} must be a list of objects")
    return rows


def validate_mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def validate_proposal_inputs(payload: object, confidence: object) -> tuple[dict[str, Any], float]:
    if not isinstance(payload, dict):
        raise ValueError("proposal payload must be an object")
    try:
        confidence_decimal = Decimal(str(confidence))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("proposal confidence must be numeric") from exc
    confidence_value = float(confidence_decimal)
    if not math.isfinite(confidence_value):
        raise ValueError("proposal confidence must be finite")
    if confidence_value < 0 or confidence_value > 1:
        raise ValueError("proposal confidence must be between 0 and 1")
    return payload, confidence_value


def validate_semantic_search_inputs(
    query: str,
    query_embedding: object,
) -> tuple[str, list[float] | None]:
    normalized_query = str(query).strip()
    if not normalized_query:
        raise ValueError("query must not be empty")
    if query_embedding is None:
        return normalized_query, None
    if not isinstance(query_embedding, list):
        raise ValueError("query_embedding must be a list of finite numbers")
    values: list[float] = []
    for value in query_embedding:
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("query_embedding must be a list of finite numbers") from exc
        if not math.isfinite(numeric):
            raise ValueError("query_embedding must be a list of finite numbers")
        values.append(numeric)
    return normalized_query, values


class CoreService:
    def __init__(self, store: CoreStore, factor_specs: dict[str, FactorSpec] | None = None) -> None:
        self.store = store
        self.factor_specs = factor_specs or {}

    def get_market_data(self, symbol: str, as_of_date: date) -> dict[str, Any]:
        symbol = require_non_empty_text(symbol, "symbol")
        rows = self.store.get_market_data(symbol, as_of_date=as_of_date)
        return rows[-1] if rows else {}

    def get_financials(self, symbol: str, period: str, as_of_date: date) -> dict[str, Any]:
        symbol = require_non_empty_text(symbol, "symbol")
        period = require_non_empty_text(period, "period")
        return self.store.get_financials(symbol, period, as_of_date)

    def get_index_constituents(self, index_code: str, as_of_date: date) -> list[dict[str, Any]]:
        index_code = require_non_empty_text(index_code, "index_code")
        require_as_of(as_of_date)
        return self.store.get_index_constituents(index_code, as_of_date)

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
        sha256 = require_non_empty_text(sha256, "sha256")
        return self.store.get_uploaded_doc(sha256)

    def compute_factors(
        self,
        factor_ids: list[str],
        start_date: date,
        end_date: date,
        as_of_date: date,
    ) -> list[dict[str, Any]]:
        factor_ids = validate_factor_ids(factor_ids)
        require_as_of(as_of_date)
        require_valid_date_range(start_date, end_date)
        assert_not_after(end_date, as_of_date)
        supported = DUCKDB_SUPPORTED_FACTORS | FUNDAMENTAL_PIT_FACTORS
        unknown = set(factor_ids) - supported
        if unknown:
            raise ValueError(f"unsupported factor ids: {sorted(unknown)}")
        self._reject_non_historical_factor_windows(factor_ids)
        outputs: list[dict[str, Any]] = []
        duckdb_factor_ids = [factor_id for factor_id in factor_ids if factor_id in DUCKDB_SUPPORTED_FACTORS]
        if duckdb_factor_ids:
            frame = self.store.load_daily()
            if not frame.empty:
                frame = frame[frame["date"] <= end_date]
                frame = frame[frame["date"] <= as_of_date]
                frame = self._bound_duckdb_history(frame, duckdb_factor_ids, start_date)
                outputs.extend(
                    compute_duckdb_factor_values(
                        frame,
                        factor_ids=duckdb_factor_ids,
                        start_date=start_date,
                        end_date=end_date,
                        as_of_date=as_of_date,
                        temp_directory=getattr(self.store, "root", "."),
                        preprocess=self._duckdb_preprocess_steps(duckdb_factor_ids),
                    )
                )
        fundamental_factor_ids = [factor_id for factor_id in factor_ids if factor_id in FUNDAMENTAL_PIT_COMPUTERS]
        if fundamental_factor_ids:
            financials = self.store.load_financials()
            for factor_id in fundamental_factor_ids:
                outputs.extend(
                    FUNDAMENTAL_PIT_COMPUTERS[factor_id](
                        financials,
                        start_date=start_date,
                        end_date=end_date,
                        as_of_date=as_of_date,
                    )
                )
        self.store.save_factor_values(outputs)
        return outputs

    def _factor_frame_to_records(
        self,
        frame: Any,
        factor_id: str,
        value_column: str,
        as_of_date: date,
    ) -> list[dict[str, Any]]:
        return factor_frame_to_records(frame, factor_id, value_column, as_of_date)

    def _duckdb_preprocess_steps(self, factor_ids: list[str]) -> list[str]:
        steps: list[str] = []
        for factor_id in factor_ids:
            spec = self.factor_specs.get(factor_id)
            if spec is None:
                continue
            for step in spec.preprocess:
                if step not in steps:
                    steps.append(step)
        return steps

    def _bound_duckdb_history(
        self,
        frame: Any,
        factor_ids: list[str],
        start_date: date,
    ) -> Any:
        lookback_days = self._duckdb_lookback_days(factor_ids)
        if lookback_days <= 0 or frame.empty:
            return frame
        cutoff = start_date - timedelta(days=lookback_days)
        return frame[frame["date"] >= cutoff]

    def _duckdb_lookback_days(self, factor_ids: list[str]) -> int:
        lookbacks: list[int] = []
        for factor_id in factor_ids:
            built_in_window = DUCKDB_FACTOR_WINDOWS.get(factor_id, 0)
            spec = self.factor_specs.get(factor_id)
            if spec is not None and spec.lookback_days is not None:
                lookbacks.append(max(spec.lookback_days, built_in_window))
            else:
                lookbacks.append(built_in_window)
        return max(lookbacks, default=0)

    def _reject_non_historical_factor_windows(self, factor_ids: list[str]) -> None:
        for factor_id in factor_ids:
            spec = self.factor_specs.get(factor_id)
            if spec is not None and spec.window_type != "historical":
                raise LookAheadViolation(f"{factor_id} uses unsupported {spec.window_type} window")

    def get_factor_values(
        self,
        factor_ids: list[str],
        start_date: date,
        end_date: date,
        as_of_date: date,
    ) -> list[dict[str, Any]]:
        factor_ids = validate_factor_ids(factor_ids)
        require_as_of(as_of_date)
        require_valid_date_range(start_date, end_date)
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
        require_valid_date_range(start_date, end_date)
        assert_not_after(end_date, as_of_date)
        if strategy_name != "buy_and_hold":
            raise ValueError(f"unsupported strategy: {strategy_name}")
        symbol, target_weight, initial_cash, execution_config = validate_backtest_parameters(parameters)
        rows = self.store.get_market_data(symbol, start_date, end_date, as_of_date)
        if not rows:
            raise DataSourceError(f"no market data for {symbol} between {start_date} and {end_date}")
        result = run_daily_backtest(
            rows,
            BuyAndHoldStrategy(symbol, target_weight),
            initial_cash,
            execution_config,
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
            orders=result.orders,
        )
        return {"backtest_result_id": self.store.save_backtest_result(report)}

    def get_backtest_result(self, backtest_result_id: str) -> dict[str, Any]:
        backtest_result_id = require_non_empty_text(backtest_result_id, "backtest_result_id")
        return self.store.get_backtest_result(backtest_result_id)

    def submit_proposal(
        self,
        kind: str,
        payload: dict[str, Any],
        source: str,
        confidence: float,
        snapshot_id: int | None = None,
    ) -> int:
        kind = require_non_empty_text(kind, "kind")
        source = require_non_empty_text(source, "source")
        snapshot_id = require_optional_positive_integer_id(snapshot_id, "snapshot_id")
        payload, confidence = validate_proposal_inputs(payload, confidence)
        errors = validate_structure(kind, payload)
        if errors:
            raise ValueError("; ".join(errors))
        proposal = Proposal(
            kind=cast(ProposalKind, kind),
            payload=payload,
            source=source,
            confidence=confidence,
            snapshot_id=snapshot_id,
        )
        return self.store.submit_proposal(proposal)

    def get_proposal_status(self, proposal_id: int) -> dict[str, Any]:
        proposal_id = require_positive_integer_id(proposal_id, "proposal_id")
        return self.store.get_proposal_status(proposal_id)

    def review_proposal(
        self,
        proposal_id: int,
        status: str,
        reviewed_by: str,
        reason: str = "",
        backtest_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        proposal_id = require_positive_integer_id(proposal_id, "proposal_id")
        require_audit_identity(reviewed_by, "reviewed_by")
        review = ProposalReview(
            proposal_id=proposal_id,
            status=ProposalStatus(status),
            reviewed_by=reviewed_by,
            reason=reason,
            backtest_result=backtest_result,
        )
        return self.store.review_proposal(review)

    def approve_proposal(self, proposal_id: int, approver_id: str, decision: str) -> dict[str, Any]:
        proposal_id = require_positive_integer_id(proposal_id, "proposal_id")
        require_audit_identity(approver_id, "approver_id")
        decision = require_approval_decision(decision)
        return self.store.approve_proposal(proposal_id, approver_id, decision)

    def create_universe_node(
        self,
        node_id: str,
        label: str,
        level: str,
        created_by: str,
        as_of_date: date,
    ) -> dict[str, Any]:
        node = UniverseBuilder().add_node(node_id, label, level, created_by, as_of_date)
        self.store.save_universe_node(node)
        return node

    def create_universe_edge(
        self,
        parent_id: str,
        child_id: str,
        relation_type: str,
        created_by: str,
        as_of_date: date,
    ) -> dict[str, Any]:
        edge = universe_edge_record(parent_id, child_id, relation_type, created_by, as_of_date)
        edge.pop("edge_id", None)
        edge["edge_id"] = self.store.save_universe_edge(edge)
        return edge

    def verify_universe_edge(self, edge_id: int, verified_by: str, as_of_date: date) -> dict[str, Any]:
        edge_id = require_positive_integer_id(edge_id, "edge_id")
        require_audit_identity(verified_by, "verified_by")
        return self.store.verify_universe_edge(edge_id, verified_by, as_of_date)

    def retire_universe_edge(self, edge_id: int, retired_by: str, as_of_date: date) -> dict[str, Any]:
        edge_id = require_positive_integer_id(edge_id, "edge_id")
        require_audit_identity(retired_by, "retired_by")
        return self.store.retire_universe_edge(edge_id, retired_by, as_of_date)

    def get_universe_children(self, parent_id: str, as_of_date: date) -> list[str]:
        parent_id = require_non_empty_text(parent_id, "parent_id")
        require_as_of(as_of_date)
        return self.store.get_universe_children_as_of(parent_id, as_of_date)

    def search_semantic_nodes(
        self,
        query: str,
        as_of_date: date,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        require_as_of(as_of_date)
        query, query_embedding = validate_semantic_search_inputs(query, query_embedding)
        return self.store.search_semantic_nodes(query, as_of_date, query_embedding)

    def scan_intraday_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return scan_cep_events(events, load_cep_rules())

    def scan_drawdown_risk(
        self,
        nav: list[dict[str, Any]],
        warn_threshold: str | Decimal = Decimal("0.05"),
        red_threshold: str | Decimal = Decimal("0.10"),
    ) -> dict[str, Any]:
        return scan_drawdown_risk_payload(nav, warn_threshold, red_threshold)

    def scan_portfolio_risk(
        self,
        *,
        cash: str | Decimal,
        positions: dict[str, Any],
        prices: dict[str, Any],
        max_gross_exposure: str | Decimal = Decimal("1"),
        max_single_position_weight: str | Decimal = Decimal("0.30"),
    ) -> dict[str, Any]:
        return scan_portfolio_risk_payload(
            cash=cash,
            positions=positions,
            prices=prices,
            max_gross_exposure=max_gross_exposure,
            max_single_position_weight=max_single_position_weight,
        )


class AsyncCoreService:
    def __init__(self, store: AsyncCoreStore, factor_specs: dict[str, FactorSpec] | None = None) -> None:
        self.store = store
        self.factor_specs = factor_specs or {}

    async def get_market_data(self, symbol: str, as_of_date: date) -> dict[str, Any]:
        symbol = require_non_empty_text(symbol, "symbol")
        rows = await self.store.get_market_data(symbol, as_of_date=as_of_date)
        return rows[-1] if rows else {}

    async def get_financials(self, symbol: str, period: str, as_of_date: date) -> dict[str, Any]:
        symbol = require_non_empty_text(symbol, "symbol")
        period = require_non_empty_text(period, "period")
        return await self.store.get_financials(symbol, period, as_of_date)

    async def get_index_constituents(self, index_code: str, as_of_date: date) -> list[dict[str, Any]]:
        index_code = require_non_empty_text(index_code, "index_code")
        require_as_of(as_of_date)
        return await self.store.get_index_constituents(index_code, as_of_date)

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
        sha256 = require_non_empty_text(sha256, "sha256")
        return await self.store.get_uploaded_doc(sha256)

    async def compute_factors(
        self,
        factor_ids: list[str],
        start_date: date,
        end_date: date,
        as_of_date: date,
    ) -> list[dict[str, Any]]:
        factor_ids = validate_factor_ids(factor_ids)
        require_as_of(as_of_date)
        require_valid_date_range(start_date, end_date)
        assert_not_after(end_date, as_of_date)
        supported = DUCKDB_SUPPORTED_FACTORS | FUNDAMENTAL_PIT_FACTORS
        unknown = set(factor_ids) - supported
        if unknown:
            raise ValueError(f"unsupported factor ids: {sorted(unknown)}")
        self._reject_non_historical_factor_windows(factor_ids)
        outputs: list[dict[str, Any]] = []
        duckdb_factor_ids = [factor_id for factor_id in factor_ids if factor_id in DUCKDB_SUPPORTED_FACTORS]
        if duckdb_factor_ids:
            frame = await self.store.load_daily()
            if not frame.empty:
                frame = frame[frame["date"] <= end_date]
                frame = frame[frame["date"] <= as_of_date]
                frame = self._bound_duckdb_history(frame, duckdb_factor_ids, start_date)
                outputs.extend(
                    compute_duckdb_factor_values(
                        frame,
                        factor_ids=duckdb_factor_ids,
                        start_date=start_date,
                        end_date=end_date,
                        as_of_date=as_of_date,
                        temp_directory=".",
                        preprocess=self._duckdb_preprocess_steps(duckdb_factor_ids),
                    )
                )
        fundamental_factor_ids = [factor_id for factor_id in factor_ids if factor_id in FUNDAMENTAL_PIT_COMPUTERS]
        if fundamental_factor_ids:
            financials = await self.store.load_financials()
            for factor_id in fundamental_factor_ids:
                outputs.extend(
                    FUNDAMENTAL_PIT_COMPUTERS[factor_id](
                        financials,
                        start_date=start_date,
                        end_date=end_date,
                        as_of_date=as_of_date,
                    )
                )
        await self.store.save_factor_values(outputs)
        return outputs

    def _duckdb_preprocess_steps(self, factor_ids: list[str]) -> list[str]:
        steps: list[str] = []
        for factor_id in factor_ids:
            spec = self.factor_specs.get(factor_id)
            if spec is None:
                continue
            for step in spec.preprocess:
                if step not in steps:
                    steps.append(step)
        return steps

    def _bound_duckdb_history(
        self,
        frame: Any,
        factor_ids: list[str],
        start_date: date,
    ) -> Any:
        lookback_days = self._duckdb_lookback_days(factor_ids)
        if lookback_days <= 0 or frame.empty:
            return frame
        cutoff = start_date - timedelta(days=lookback_days)
        return frame[frame["date"] >= cutoff]

    def _duckdb_lookback_days(self, factor_ids: list[str]) -> int:
        lookbacks: list[int] = []
        for factor_id in factor_ids:
            built_in_window = DUCKDB_FACTOR_WINDOWS.get(factor_id, 0)
            spec = self.factor_specs.get(factor_id)
            if spec is not None and spec.lookback_days is not None:
                lookbacks.append(max(spec.lookback_days, built_in_window))
            else:
                lookbacks.append(built_in_window)
        return max(lookbacks, default=0)

    def _reject_non_historical_factor_windows(self, factor_ids: list[str]) -> None:
        for factor_id in factor_ids:
            spec = self.factor_specs.get(factor_id)
            if spec is not None and spec.window_type != "historical":
                raise LookAheadViolation(f"{factor_id} uses unsupported {spec.window_type} window")

    async def get_factor_values(
        self,
        factor_ids: list[str],
        start_date: date,
        end_date: date,
        as_of_date: date,
    ) -> list[dict[str, Any]]:
        factor_ids = validate_factor_ids(factor_ids)
        require_as_of(as_of_date)
        require_valid_date_range(start_date, end_date)
        assert_not_after(end_date, as_of_date)
        return await self.store.get_factor_values(factor_ids, start_date, end_date, as_of_date)

    async def run_backtest(
        self,
        strategy_name: str,
        start_date: date,
        end_date: date,
        parameters: dict[str, Any],
        as_of_date: date,
    ) -> dict[str, Any]:
        require_as_of(as_of_date)
        require_valid_date_range(start_date, end_date)
        assert_not_after(end_date, as_of_date)
        if strategy_name != "buy_and_hold":
            raise ValueError(f"unsupported strategy: {strategy_name}")
        symbol, target_weight, initial_cash, execution_config = validate_backtest_parameters(parameters)
        rows = await self.store.get_market_data(symbol, start_date, end_date, as_of_date)
        if not rows:
            raise DataSourceError(f"no market data for {symbol} between {start_date} and {end_date}")
        result = run_daily_backtest(
            rows,
            BuyAndHoldStrategy(symbol, target_weight),
            initial_cash,
            execution_config,
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
            orders=result.orders,
        )
        return {"backtest_result_id": await self.store.save_backtest_result(report)}

    async def get_backtest_result(self, backtest_result_id: str) -> dict[str, Any]:
        backtest_result_id = require_non_empty_text(backtest_result_id, "backtest_result_id")
        return await self.store.get_backtest_result(backtest_result_id)

    async def submit_proposal(
        self,
        kind: str,
        payload: dict[str, Any],
        source: str,
        confidence: float,
        snapshot_id: int | None = None,
    ) -> int:
        kind = require_non_empty_text(kind, "kind")
        source = require_non_empty_text(source, "source")
        snapshot_id = require_optional_positive_integer_id(snapshot_id, "snapshot_id")
        payload, confidence = validate_proposal_inputs(payload, confidence)
        errors = validate_structure(kind, payload)
        if errors:
            raise ValueError("; ".join(errors))
        proposal = Proposal(
            kind=cast(ProposalKind, kind),
            payload=payload,
            source=source,
            confidence=confidence,
            snapshot_id=snapshot_id,
        )
        return await self.store.submit_proposal(proposal)

    async def get_proposal_status(self, proposal_id: int) -> dict[str, Any]:
        proposal_id = require_positive_integer_id(proposal_id, "proposal_id")
        return await self.store.get_proposal_status(proposal_id)

    async def review_proposal(
        self,
        proposal_id: int,
        status: str,
        reviewed_by: str,
        reason: str = "",
        backtest_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        proposal_id = require_positive_integer_id(proposal_id, "proposal_id")
        require_audit_identity(reviewed_by, "reviewed_by")
        review = ProposalReview(
            proposal_id=proposal_id,
            status=ProposalStatus(status),
            reviewed_by=reviewed_by,
            reason=reason,
            backtest_result=backtest_result,
        )
        return await self.store.review_proposal(review)

    async def approve_proposal(self, proposal_id: int, approver_id: str, decision: str) -> dict[str, Any]:
        proposal_id = require_positive_integer_id(proposal_id, "proposal_id")
        require_audit_identity(approver_id, "approver_id")
        decision = require_approval_decision(decision)
        return await self.store.approve_proposal(proposal_id, approver_id, decision)

    async def create_universe_node(
        self,
        node_id: str,
        label: str,
        level: str,
        created_by: str,
        as_of_date: date,
    ) -> dict[str, Any]:
        node = UniverseBuilder().add_node(node_id, label, level, created_by, as_of_date)
        await self.store.save_universe_node(node)
        return node

    async def create_universe_edge(
        self,
        parent_id: str,
        child_id: str,
        relation_type: str,
        created_by: str,
        as_of_date: date,
    ) -> dict[str, Any]:
        edge = universe_edge_record(parent_id, child_id, relation_type, created_by, as_of_date)
        edge.pop("edge_id", None)
        edge["edge_id"] = await self.store.save_universe_edge(edge)
        return edge

    async def verify_universe_edge(self, edge_id: int, verified_by: str, as_of_date: date) -> dict[str, Any]:
        edge_id = require_positive_integer_id(edge_id, "edge_id")
        require_audit_identity(verified_by, "verified_by")
        return await self.store.verify_universe_edge(edge_id, verified_by, as_of_date)

    async def retire_universe_edge(self, edge_id: int, retired_by: str, as_of_date: date) -> dict[str, Any]:
        edge_id = require_positive_integer_id(edge_id, "edge_id")
        require_audit_identity(retired_by, "retired_by")
        return await self.store.retire_universe_edge(edge_id, retired_by, as_of_date)

    async def get_universe_children(self, parent_id: str, as_of_date: date) -> list[str]:
        parent_id = require_non_empty_text(parent_id, "parent_id")
        require_as_of(as_of_date)
        return await self.store.get_universe_children_as_of(parent_id, as_of_date)

    async def search_semantic_nodes(
        self,
        query: str,
        as_of_date: date,
        query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        require_as_of(as_of_date)
        query, query_embedding = validate_semantic_search_inputs(query, query_embedding)
        return await self.store.search_semantic_nodes(query, as_of_date, query_embedding)

    async def scan_intraday_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return scan_cep_events(events, load_cep_rules())

    async def scan_drawdown_risk(
        self,
        nav: list[dict[str, Any]],
        warn_threshold: str | Decimal = Decimal("0.05"),
        red_threshold: str | Decimal = Decimal("0.10"),
    ) -> dict[str, Any]:
        return scan_drawdown_risk_payload(nav, warn_threshold, red_threshold)

    async def scan_portfolio_risk(
        self,
        *,
        cash: str | Decimal,
        positions: dict[str, Any],
        prices: dict[str, Any],
        max_gross_exposure: str | Decimal = Decimal("1"),
        max_single_position_weight: str | Decimal = Decimal("0.30"),
    ) -> dict[str, Any]:
        return scan_portfolio_risk_payload(
            cash=cash,
            positions=positions,
            prices=prices,
            max_gross_exposure=max_gross_exposure,
            max_single_position_weight=max_single_position_weight,
        )


def factor_frame_to_records(
    frame: Any,
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


def parse_nav_points(rows: list[dict[str, Any]]) -> list[tuple[date, Decimal]]:
    rows = validate_record_list(rows, "nav")
    points: list[tuple[date, Decimal]] = []
    previous_day: date | None = None
    for row in rows:
        if "date" not in row:
            raise ValueError("nav row requires date")
        raw_day = row["date"]
        try:
            day = raw_day if isinstance(raw_day, date) else date.fromisoformat(str(raw_day))
        except ValueError as exc:
            raise ValueError("nav row date must be an ISO date") from exc
        if previous_day is not None and day <= previous_day:
            raise ValueError("nav row dates must be strictly increasing")
        raw_nav = row.get("nav", row.get("value"))
        if raw_nav is None:
            raise ValueError("nav row requires nav or value")
        try:
            nav_value = Decimal(str(raw_nav))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("nav row value must be a decimal") from exc
        if not nav_value.is_finite():
            raise ValueError("nav row value must be finite")
        if nav_value <= 0:
            raise ValueError("nav row value must be positive")
        points.append((day, nav_value))
        previous_day = day
    return points


def scan_drawdown_risk_payload(
    nav: list[dict[str, Any]],
    warn_threshold: str | Decimal = Decimal("0.05"),
    red_threshold: str | Decimal = Decimal("0.10"),
) -> dict[str, Any]:
    return dict(
        scan_drawdown_risk_report(
            parse_nav_points(nav),
            warn_threshold=parse_non_negative_finite_threshold(warn_threshold, "warn_threshold"),
            red_threshold=parse_non_negative_finite_threshold(red_threshold, "red_threshold"),
        )
    )


def parse_non_negative_finite_threshold(value: str | Decimal, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be decimal-compatible") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    if parsed < 0:
        raise ValueError(f"{field} must be non-negative")
    return parsed


def scan_portfolio_risk_payload(
    *,
    cash: str | Decimal,
    positions: dict[str, Any],
    prices: dict[str, Any],
    max_gross_exposure: str | Decimal = Decimal("1"),
    max_single_position_weight: str | Decimal = Decimal("0.30"),
) -> dict[str, Any]:
    positions = validate_mapping(positions, "positions")
    prices = validate_mapping(prices, "prices")
    position_quantities: dict[str, int] = {}
    for symbol, quantity in positions.items():
        try:
            position_quantities[symbol] = int(quantity)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"position quantity for {symbol} must be an integer") from exc
    missing_prices = sorted(set(position_quantities) - set(prices))
    if missing_prices:
        raise ValueError(f"prices missing symbols: {missing_prices}")
    try:
        cash_value = Decimal(str(cash))
        price_values = {symbol: Decimal(str(price)) for symbol, price in prices.items()}
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("portfolio risk inputs must be decimal-compatible") from exc
    max_gross = parse_non_negative_finite_threshold(max_gross_exposure, "max_gross_exposure")
    max_single = parse_non_negative_finite_threshold(max_single_position_weight, "max_single_position_weight")
    if not cash_value.is_finite():
        raise ValueError("cash must be finite")
    for symbol, price in price_values.items():
        if not price.is_finite():
            raise ValueError(f"price for {symbol} must be finite")
    portfolio = Portfolio(
        cash=cash_value,
        positions=position_quantities,
    )
    return dict(
        scan_portfolio_risk_report(
            portfolio,
            price_values,
            max_gross_exposure=max_gross,
            max_single_position_weight=max_single,
        )
    )


def universe_edge_record(
    parent_id: str,
    child_id: str,
    relation_type: str,
    created_by: str,
    as_of_date: date,
) -> dict[str, Any]:
    builder = UniverseBuilder()
    builder.add_node(parent_id, parent_id, "validated", created_by, as_of_date)
    builder.add_node(child_id, child_id, "validated", created_by, as_of_date)
    return builder.add_edge(parent_id, child_id, relation_type, created_by, as_of_date)
