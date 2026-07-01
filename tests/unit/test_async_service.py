import base64
from datetime import date

import pandas as pd
import pytest

from aeqcs.core.exceptions import LookAheadViolation
from aeqcs.core.exceptions import DocumentParseError
from aeqcs.core.service import AsyncCoreService
from aeqcs.factor.registry import FactorSpec


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class FakeAsyncStore:
    def __init__(self) -> None:
        self.saved_document = None
        self.saved_chunks = []
        self.uploaded_doc_query = None
        self.proposals = []
        self.saved_factors = []
        self.saved_backtest = None
        self.backtest_result_query = None
        self.factor_query = None
        self.market_query = None
        self.saved_universe_nodes = []
        self.saved_universe_edges = []
        self.universe_children_query = None
        self.index_constituents_query = None
        self.approve_called = False
        self.semantic_search_query = None

    async def load_daily(self):
        return pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "date": date(2026, 1, 1),
                    "open": 10,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10,
                    "volume": 1000,
                    "amount": 10000,
                },
                {
                    "symbol": "000001",
                    "date": date(2026, 1, 2),
                    "open": 11,
                    "high": 12.2,
                    "low": 10.8,
                    "close": 12,
                    "volume": 1200,
                    "amount": 13200,
                },
            ]
        )

    async def load_financials(self):
        return pd.DataFrame(
            [
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": date(2026, 1, 1),
                    "vintage": 0,
                    "roe": 0.10,
                    "debt_ratio": 0.42,
                    "profit_yoy": 0.18,
                    "current_ratio": 1.35,
                    "quick_ratio": 1.08,
                    "revenue_yoy": 0.12,
                    "eps": 0.88,
                    "bps": 5.10,
                    "gross_margin": 0.31,
                    "net_margin": 0.17,
                },
                {
                    "symbol": "000001",
                    "period": "2025Q4",
                    "ann_date": date(2026, 1, 10),
                    "vintage": 1,
                    "roe": 0.12,
                    "debt_ratio": 0.50,
                    "profit_yoy": 0.22,
                    "current_ratio": 1.50,
                    "quick_ratio": 1.22,
                    "revenue_yoy": 0.16,
                    "eps": 0.92,
                    "bps": 5.30,
                    "gross_margin": 0.36,
                    "net_margin": 0.19,
                },
            ]
        )

    async def get_market_data(self, symbol, start_date=None, end_date=None, as_of_date=None):
        self.market_query = (symbol, start_date, end_date, as_of_date)
        return [
            {
                "symbol": symbol,
                "date": date(2026, 1, 2),
                "open": 11,
                "high": 12.2,
                "low": 10.8,
                "close": 12,
                "volume": 1200,
                "amount": 13200,
            }
        ]

    async def get_financials(self, symbol, period, as_of_date=None):
        return {"symbol": symbol, "period": period, "roe": 0.12, "ann_date": date(2026, 1, 2)}

    async def save_uploaded_doc(self, document, chunks):
        self.saved_document = document
        self.saved_chunks = list(chunks)
        return {"doc_id": 7, "sha256": document.sha256, "chunks": len(chunks)}

    async def submit_proposal(self, proposal):
        self.proposals.append(proposal)
        return len(self.proposals)

    async def get_proposal_status(self, proposal_id):
        return {"proposal_id": proposal_id, "status": "pending"}

    async def review_proposal(self, review):
        return {"proposal_id": review.proposal_id, "status": review.status.value}

    async def approve_proposal(self, proposal_id, approver_id, decision):
        self.approve_called = True
        return {"proposal_id": proposal_id, "reviewed_by": approver_id, "decision": decision}

    async def save_backtest_result(self, report):
        self.saved_backtest = report
        return report.backtest_result_id

    async def get_backtest_result(self, backtest_result_id):
        self.backtest_result_query = backtest_result_id
        return {"backtest_result_id": backtest_result_id}

    async def save_factor_values(self, values):
        self.saved_factors = list(values)
        return len(values)

    async def get_factor_values(self, factor_ids, start_date, end_date, as_of_date):
        self.factor_query = (factor_ids, start_date, end_date, as_of_date)
        return [{"factor_id": factor_ids[0], "date": start_date, "value": 0.2}]

    async def get_uploaded_doc(self, sha256):
        self.uploaded_doc_query = sha256
        return {"sha256": sha256}

    async def save_universe_node(self, node):
        self.saved_universe_nodes.append(node)
        return node["node_id"]

    async def save_universe_edge(self, edge):
        self.saved_universe_edges.append(edge)
        return len(self.saved_universe_edges)

    async def verify_universe_edge(self, edge_id, verified_by, as_of_date):
        return {"edge_id": edge_id, "verified": True, "verified_by": verified_by, "verified_as_of": as_of_date}

    async def retire_universe_edge(self, edge_id, retired_by, as_of_date):
        return {"edge_id": edge_id, "retired_by": retired_by, "valid_to": as_of_date}

    async def get_universe_children_as_of(self, parent_id, as_of_date):
        self.universe_children_query = (parent_id, as_of_date)
        return ["stock.000001"]

    async def get_index_constituents(self, index_code, as_of_date):
        self.index_constituents_query = (index_code, as_of_date)
        return [{"index_code": index_code, "symbol": "000001", "in_date": as_of_date, "out_date": None}]

    async def search_semantic_nodes(self, query, as_of_date, query_embedding=None):
        self.semantic_search_query = (query, as_of_date, query_embedding)
        return [{"node_id": "concept.ai", "label": "AI", "score": 1.0}]


@pytest.mark.asyncio
async def test_async_load_inbox_saves_doc_chunks_and_proposals():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    result = await service.load_inbox(
        "pg-note.md",
        b64("factor: async_momentum = close / ref(close, 1) - 1"),
    )

    assert result["doc_id"] == 7
    assert result["chunks"] == 1
    assert result["proposal_ids"] == [1]
    assert store.saved_document.filename == "pg-note.md"
    assert store.saved_document.path == "upload://pg-note.md"
    assert store.saved_chunks[0].text.startswith("factor: async_momentum")
    assert store.proposals[0].source == "upload:pg-note.md"


@pytest.mark.asyncio
async def test_async_load_inbox_rejects_unsafe_filename():
    service = AsyncCoreService(FakeAsyncStore())

    with pytest.raises(DocumentParseError):
        await service.load_inbox("../evil.md", b64("text"))


@pytest.mark.asyncio
async def test_async_uploaded_doc_rejects_empty_sha256_before_store_call():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    with pytest.raises(ValueError, match="sha256 is required"):
        await service.get_uploaded_doc(" ")

    assert store.uploaded_doc_query is None


@pytest.mark.asyncio
async def test_async_submit_proposal_requires_object_payload_and_valid_confidence():
    service = AsyncCoreService(FakeAsyncStore())

    with pytest.raises(ValueError, match="proposal payload must be an object"):
        await service.submit_proposal("edge", "parent_id=banking", "test", 0.8)

    with pytest.raises(ValueError, match="proposal confidence must be finite"):
        await service.submit_proposal(
            "edge",
            {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
            "test",
            float("nan"),
        )

    with pytest.raises(ValueError, match="proposal confidence must be between 0 and 1"):
        await service.submit_proposal(
            "edge",
            {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
            "test",
            1.5,
        )


@pytest.mark.asyncio
async def test_async_submit_proposal_requires_source_before_store_call():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    with pytest.raises(ValueError, match="source is required"):
        await service.submit_proposal(
            "edge",
            {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
            " ",
            0.8,
        )

    assert store.proposals == []


@pytest.mark.asyncio
async def test_async_submit_proposal_requires_kind_before_store_call():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    with pytest.raises(ValueError, match="kind is required"):
        await service.submit_proposal(
            " ",
            {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
            "test",
            0.8,
        )

    assert store.proposals == []


@pytest.mark.asyncio
async def test_async_submit_proposal_rejects_invalid_snapshot_id_before_store_call():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    with pytest.raises(ValueError, match="snapshot_id must be a positive integer"):
        await service.submit_proposal(
            "edge",
            {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
            "test",
            0.8,
            snapshot_id=0,
        )

    assert store.proposals == []


@pytest.mark.asyncio
async def test_async_review_proposal_requires_auditable_identity():
    service = AsyncCoreService(FakeAsyncStore())

    with pytest.raises(ValueError, match="reviewed_by is required"):
        await service.review_proposal(1, "approved", " ")


@pytest.mark.asyncio
async def test_async_approve_proposal_requires_auditable_identity_before_store_call():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    with pytest.raises(ValueError, match="approver_id is required"):
        await service.approve_proposal(99, " ", "promote")

    assert store.approve_called is False


@pytest.mark.asyncio
async def test_async_approve_proposal_rejects_unsupported_decision_before_store_call():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    with pytest.raises(ValueError, match="unsupported approval decision"):
        await service.approve_proposal(99, "risk_officer", "hold")

    assert store.approve_called is False


@pytest.mark.asyncio
async def test_async_proposal_ids_must_be_positive():
    service = AsyncCoreService(FakeAsyncStore())

    with pytest.raises(ValueError, match="proposal_id must be a positive integer"):
        await service.get_proposal_status(0)

    with pytest.raises(ValueError, match="proposal_id must be a positive integer"):
        await service.review_proposal(-1, "approved", "reviewer")

    with pytest.raises(ValueError, match="proposal_id must be a positive integer"):
        await service.approve_proposal(0, "risk_officer", "promote")


@pytest.mark.asyncio
async def test_async_market_data_and_financials_use_store():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    market = await service.get_market_data("000001", date(2026, 1, 2))
    financials = await service.get_financials("000001", "2025Q4", date(2026, 1, 2))

    assert market["close"] == 12
    assert store.market_query == ("000001", None, None, date(2026, 1, 2))
    assert financials["roe"] == 0.12


@pytest.mark.asyncio
async def test_async_service_rejects_empty_market_symbol_before_store_call():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    with pytest.raises(ValueError, match="symbol is required"):
        await service.get_market_data(" ", date(2026, 1, 2))

    assert store.market_query is None


@pytest.mark.asyncio
async def test_async_service_rejects_empty_financial_symbol_or_period_before_store_call():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    with pytest.raises(ValueError, match="symbol is required"):
        await service.get_financials("", "2025Q4", date(2026, 1, 2))

    with pytest.raises(ValueError, match="period is required"):
        await service.get_financials("000001", " ", date(2026, 1, 2))


@pytest.mark.asyncio
async def test_async_index_constituents_delegate_with_explicit_as_of():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    rows = await service.get_index_constituents("000300", date(2026, 1, 15))

    assert rows[0]["symbol"] == "000001"
    assert store.index_constituents_query == ("000300", date(2026, 1, 15))


@pytest.mark.asyncio
async def test_async_index_constituents_rejects_empty_index_code_before_store_call():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    with pytest.raises(ValueError, match="index_code is required"):
        await service.get_index_constituents(" ", date(2026, 1, 15))

    assert store.index_constituents_query is None


@pytest.mark.asyncio
async def test_async_semantic_node_search_rejects_invalid_query_embedding():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    with pytest.raises(ValueError, match="query must not be empty"):
        await service.search_semantic_nodes(" ", date(2026, 1, 15))

    with pytest.raises(ValueError, match="query_embedding must be a list of finite numbers"):
        await service.search_semantic_nodes("AI", date(2026, 1, 15), "0.1,0.2")

    with pytest.raises(ValueError, match="query_embedding must be a list of finite numbers"):
        await service.search_semantic_nodes("AI", date(2026, 1, 15), [0.1, float("inf")])

    assert store.semantic_search_query is None


@pytest.mark.asyncio
async def test_async_factor_tools_match_core_guardrails():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    values = await service.compute_factors(
        ["momentum_1d"],
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 2),
    )
    stored = await service.get_factor_values(
        ["momentum_1d"],
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 2),
    )

    assert values
    assert store.saved_factors == values
    assert stored[0]["factor_id"] == "momentum_1d"
    assert store.factor_query == (
        ["momentum_1d"],
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 2),
    )

    with pytest.raises(LookAheadViolation):
        await service.get_factor_values(
            ["momentum_1d"],
            date(2026, 1, 1),
            date(2026, 1, 3),
            date(2026, 1, 2),
        )


@pytest.mark.asyncio
async def test_async_services_reject_start_date_after_end_date():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    with pytest.raises(ValueError, match="start_date must be on or before end_date"):
        await service.compute_factors(
            ["momentum_1d"],
            date(2026, 1, 3),
            date(2026, 1, 2),
            date(2026, 1, 3),
        )

    with pytest.raises(ValueError, match="start_date must be on or before end_date"):
        await service.get_factor_values(
            ["momentum_1d"],
            date(2026, 1, 3),
            date(2026, 1, 2),
            date(2026, 1, 3),
        )

    with pytest.raises(ValueError, match="start_date must be on or before end_date"):
        await service.run_backtest(
            "buy_and_hold",
            date(2026, 1, 3),
            date(2026, 1, 2),
            {"symbol": "000001"},
            date(2026, 1, 3),
        )

    assert store.factor_query is None
    assert store.market_query is None


@pytest.mark.asyncio
async def test_async_factor_ids_must_be_non_empty_string_list():
    service = AsyncCoreService(FakeAsyncStore())

    with pytest.raises(ValueError, match="factor_ids must be a list of non-empty strings"):
        await service.compute_factors(
            "momentum_1d",
            date(2026, 1, 1),
            date(2026, 1, 2),
            date(2026, 1, 2),
        )

    with pytest.raises(ValueError, match="factor_ids must be a list of non-empty strings"):
        await service.get_factor_values(
            ["momentum_1d", ""],
            date(2026, 1, 1),
            date(2026, 1, 2),
            date(2026, 1, 2),
        )


@pytest.mark.asyncio
async def test_async_compute_factors_supports_roe_quarterly_pit_factor():
    store = FakeAsyncStore()
    service = AsyncCoreService(
        store,
        factor_specs={
            "roe_quarterly": FactorSpec(
                factor_id="roe_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.roe",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    values = await service.compute_factors(
        ["roe_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert values == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "roe_quarterly",
            "version": 1,
            "value": 0.1,
            "calc_timestamp": pd.Timestamp("2026-01-05").to_pydatetime(),
        }
    ]
    assert store.saved_factors == values


@pytest.mark.asyncio
async def test_async_compute_factors_supports_debt_ratio_quarterly_pit_factor():
    store = FakeAsyncStore()
    service = AsyncCoreService(
        store,
        factor_specs={
            "debt_ratio_quarterly": FactorSpec(
                factor_id="debt_ratio_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.debt_ratio",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    values = await service.compute_factors(
        ["debt_ratio_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert values == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "debt_ratio_quarterly",
            "version": 1,
            "value": 0.42,
            "calc_timestamp": pd.Timestamp("2026-01-05").to_pydatetime(),
        }
    ]
    assert store.saved_factors == values


@pytest.mark.asyncio
async def test_async_compute_factors_supports_equity_ratio_quarterly_pit_factor():
    store = FakeAsyncStore()
    service = AsyncCoreService(
        store,
        factor_specs={
            "equity_ratio_quarterly": FactorSpec(
                factor_id="equity_ratio_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="1 - financials.debt_ratio",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    values = await service.compute_factors(
        ["equity_ratio_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert values == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "equity_ratio_quarterly",
            "version": 1,
            "value": 0.58,
            "calc_timestamp": pd.Timestamp("2026-01-05").to_pydatetime(),
        }
    ]
    assert store.saved_factors == values


@pytest.mark.asyncio
async def test_async_compute_factors_supports_debt_to_equity_quarterly_pit_factor():
    store = FakeAsyncStore()
    service = AsyncCoreService(
        store,
        factor_specs={
            "debt_to_equity_quarterly": FactorSpec(
                factor_id="debt_to_equity_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.debt_ratio / (1 - financials.debt_ratio)",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    values = await service.compute_factors(
        ["debt_to_equity_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert values == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "debt_to_equity_quarterly",
            "version": 1,
            "value": 0.724137931034,
            "calc_timestamp": pd.Timestamp("2026-01-05").to_pydatetime(),
        }
    ]
    assert store.saved_factors == values


@pytest.mark.asyncio
async def test_async_compute_factors_supports_profit_yoy_quarterly_pit_factor():
    store = FakeAsyncStore()
    service = AsyncCoreService(
        store,
        factor_specs={
            "profit_yoy_quarterly": FactorSpec(
                factor_id="profit_yoy_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.profit_yoy",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    values = await service.compute_factors(
        ["profit_yoy_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert values == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "profit_yoy_quarterly",
            "version": 1,
            "value": 0.18,
            "calc_timestamp": pd.Timestamp("2026-01-05").to_pydatetime(),
        }
    ]
    assert store.saved_factors == values


@pytest.mark.asyncio
async def test_async_compute_factors_supports_current_ratio_quarterly_pit_factor():
    store = FakeAsyncStore()
    service = AsyncCoreService(
        store,
        factor_specs={
            "current_ratio_quarterly": FactorSpec(
                factor_id="current_ratio_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.current_ratio",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    values = await service.compute_factors(
        ["current_ratio_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert values == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "current_ratio_quarterly",
            "version": 1,
            "value": 1.35,
            "calc_timestamp": pd.Timestamp("2026-01-05").to_pydatetime(),
        }
    ]
    assert store.saved_factors == values


@pytest.mark.asyncio
async def test_async_compute_factors_supports_quick_ratio_quarterly_pit_factor():
    store = FakeAsyncStore()
    service = AsyncCoreService(
        store,
        factor_specs={
            "quick_ratio_quarterly": FactorSpec(
                factor_id="quick_ratio_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.quick_ratio",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    values = await service.compute_factors(
        ["quick_ratio_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert values == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "quick_ratio_quarterly",
            "version": 1,
            "value": 1.08,
            "calc_timestamp": pd.Timestamp("2026-01-05").to_pydatetime(),
        }
    ]
    assert store.saved_factors == values


@pytest.mark.asyncio
async def test_async_compute_factors_supports_revenue_yoy_quarterly_pit_factor():
    store = FakeAsyncStore()
    service = AsyncCoreService(
        store,
        factor_specs={
            "revenue_yoy_quarterly": FactorSpec(
                factor_id="revenue_yoy_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.revenue_yoy",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    values = await service.compute_factors(
        ["revenue_yoy_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert values == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "revenue_yoy_quarterly",
            "version": 1,
            "value": 0.12,
            "calc_timestamp": pd.Timestamp("2026-01-05").to_pydatetime(),
        }
    ]
    assert store.saved_factors == values


@pytest.mark.asyncio
async def test_async_compute_factors_supports_gross_margin_quarterly_pit_factor():
    store = FakeAsyncStore()
    service = AsyncCoreService(
        store,
        factor_specs={
            "gross_margin_quarterly": FactorSpec(
                factor_id="gross_margin_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.gross_margin",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    values = await service.compute_factors(
        ["gross_margin_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert values == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "gross_margin_quarterly",
            "version": 1,
            "value": 0.31,
            "calc_timestamp": pd.Timestamp("2026-01-05").to_pydatetime(),
        }
    ]
    assert store.saved_factors == values


@pytest.mark.asyncio
async def test_async_compute_factors_supports_net_margin_quarterly_pit_factor():
    store = FakeAsyncStore()
    service = AsyncCoreService(
        store,
        factor_specs={
            "net_margin_quarterly": FactorSpec(
                factor_id="net_margin_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.net_margin",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    values = await service.compute_factors(
        ["net_margin_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert values == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "net_margin_quarterly",
            "version": 1,
            "value": 0.17,
            "calc_timestamp": pd.Timestamp("2026-01-05").to_pydatetime(),
        }
    ]
    assert store.saved_factors == values


@pytest.mark.asyncio
async def test_async_compute_factors_supports_margin_spread_quarterly_pit_factor():
    store = FakeAsyncStore()
    service = AsyncCoreService(
        store,
        factor_specs={
            "margin_spread_quarterly": FactorSpec(
                factor_id="margin_spread_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.gross_margin - financials.net_margin",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            )
        },
    )

    values = await service.compute_factors(
        ["margin_spread_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert values == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "margin_spread_quarterly",
            "version": 1,
            "value": 0.14,
            "calc_timestamp": pd.Timestamp("2026-01-05").to_pydatetime(),
        }
    ]
    assert store.saved_factors == values


@pytest.mark.asyncio
async def test_async_compute_factors_supports_per_share_quarterly_pit_factors():
    store = FakeAsyncStore()
    service = AsyncCoreService(
        store,
        factor_specs={
            "eps_quarterly": FactorSpec(
                factor_id="eps_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.eps",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            ),
            "bps_quarterly": FactorSpec(
                factor_id="bps_quarterly",
                category="fundamental",
                engine="duckdb",
                compute="financials.bps",
                window_type="historical",
                preprocess=[],
                align="ann_date",
                update_freq="quarterly",
            ),
        },
    )

    values = await service.compute_factors(
        ["eps_quarterly", "bps_quarterly"],
        date(2026, 1, 1),
        date(2026, 1, 5),
        date(2026, 1, 5),
    )

    assert values == [
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "eps_quarterly",
            "version": 1,
            "value": 0.88,
            "calc_timestamp": pd.Timestamp("2026-01-05").to_pydatetime(),
        },
        {
            "symbol": "000001",
            "date": date(2026, 1, 1),
            "factor_id": "bps_quarterly",
            "version": 1,
            "value": 5.1,
            "calc_timestamp": pd.Timestamp("2026-01-05").to_pydatetime(),
        },
    ]
    assert store.saved_factors == values


@pytest.mark.asyncio
async def test_async_backtest_persists_report():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    result = await service.run_backtest(
        "buy_and_hold",
        date(2026, 1, 1),
        date(2026, 1, 2),
        {"symbol": "000001", "initial_cash": "10000"},
        date(2026, 1, 2),
    )

    assert result["backtest_result_id"]
    assert store.saved_backtest.backtest_result_id == result["backtest_result_id"]
    assert store.market_query == ("000001", date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 2))


@pytest.mark.asyncio
async def test_async_backtest_result_rejects_empty_id_before_store_call():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    with pytest.raises(ValueError, match="backtest_result_id is required"):
        await service.get_backtest_result(" ")

    assert store.backtest_result_query is None


@pytest.mark.asyncio
async def test_async_backtest_rejects_non_positive_lot_size():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    with pytest.raises(ValueError, match="parameters.lot_size must be positive"):
        await service.run_backtest(
            "buy_and_hold",
            date(2026, 1, 1),
            date(2026, 1, 2),
            {"symbol": "000001", "lot_size": 0},
            date(2026, 1, 2),
        )

    assert store.market_query is None


@pytest.mark.asyncio
async def test_async_drawdown_risk_rejects_non_positive_nav_values():
    service = AsyncCoreService(FakeAsyncStore())

    with pytest.raises(ValueError, match="nav row value must be positive"):
        await service.scan_drawdown_risk([{"date": "2026-01-01", "nav": "0"}])

    with pytest.raises(ValueError, match="nav row value must be positive"):
        await service.scan_drawdown_risk([{"date": "2026-01-01", "nav": "-1"}])


@pytest.mark.asyncio
async def test_async_drawdown_risk_requires_strictly_increasing_dates():
    service = AsyncCoreService(FakeAsyncStore())

    with pytest.raises(ValueError, match="nav row dates must be strictly increasing"):
        await service.scan_drawdown_risk(
            [
                {"date": "2026-01-02", "nav": "100"},
                {"date": "2026-01-01", "nav": "101"},
            ]
        )


@pytest.mark.asyncio
async def test_async_universe_graph_methods_delegate_to_store():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    node = await service.create_universe_node("concept.ai", "AI", "concept", "data_steward", date(2026, 1, 1))
    edge = await service.create_universe_edge(
        "concept.ai",
        "stock.000001",
        "contains",
        "data_steward",
        date(2026, 1, 2),
    )
    verified = await service.verify_universe_edge(1, "factor_researcher", date(2026, 1, 3))
    children = await service.get_universe_children("concept.ai", date(2026, 1, 4))

    assert node["node_id"] == "concept.ai"
    assert store.saved_universe_nodes == [node]
    assert edge["edge_id"] == 1
    assert store.saved_universe_edges == [edge]
    assert verified["verified_by"] == "factor_researcher"
    assert children == ["stock.000001"]
    assert store.universe_children_query == ("concept.ai", date(2026, 1, 4))


@pytest.mark.asyncio
async def test_async_universe_children_rejects_empty_parent_id_before_store_call():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    with pytest.raises(ValueError, match="parent_id is required"):
        await service.get_universe_children(" ", date(2026, 1, 4))

    assert store.universe_children_query is None


@pytest.mark.asyncio
async def test_async_universe_edge_audit_identity_is_required():
    store = FakeAsyncStore()
    service = AsyncCoreService(store)

    with pytest.raises(ValueError, match="verified_by is required"):
        await service.verify_universe_edge(1, " ", date(2026, 1, 3))
    with pytest.raises(ValueError, match="retired_by is required"):
        await service.retire_universe_edge(1, "", date(2026, 1, 4))


@pytest.mark.asyncio
async def test_async_universe_edge_ids_must_be_positive():
    service = AsyncCoreService(FakeAsyncStore())

    with pytest.raises(ValueError, match="edge_id must be a positive integer"):
        await service.verify_universe_edge(0, "factor_researcher", date(2026, 1, 3))

    with pytest.raises(ValueError, match="edge_id must be a positive integer"):
        await service.retire_universe_edge(-1, "risk_officer", date(2026, 1, 4))
