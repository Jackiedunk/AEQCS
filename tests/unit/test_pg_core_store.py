from datetime import date, datetime

import pytest

from aeqcs.core.exceptions import LookAheadViolation
from aeqcs.gate.proposals import ProposalReview, ProposalStatus
from aeqcs.ingest.document_parser import DocumentChunk, ParsedDocument
from aeqcs.knowledge.universe_builder import UniverseBuilder
from aeqcs.store.pg_core import PgCoreStore
from aeqcs.strategy.backtest.engine import BacktestReport


class FakeConn:
    def __init__(self):
        self.calls = []

    async def fetch(self, query, *args):
        self.calls.append(("fetch", query, args))
        return []

    async def fetchrow(self, query, *args):
        self.calls.append(("fetchrow", query, args))
        if "SELECT status FROM proposals" in query:
            return {"status": "pending"}
        return None

    async def fetchval(self, query, *args):
        self.calls.append(("fetchval", query, args))
        return 1

    async def execute(self, query, *args):
        self.calls.append(("execute", query, args))
        return "OK"

    def transaction(self):
        return AcquireContext(self)


class AcquireContext:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self):
        self.conn = FakeConn()

    def acquire(self):
        return AcquireContext(self.conn)


@pytest.mark.asyncio
async def test_pg_market_data_requires_as_of():
    store = PgCoreStore(FakePool())

    with pytest.raises(LookAheadViolation):
        await store.get_market_data("000001")


@pytest.mark.asyncio
async def test_pg_market_data_binds_as_of_date():
    pool = FakePool()
    store = PgCoreStore(pool)

    await store.get_market_data("000001", as_of_date=date(2026, 1, 2))

    kind, query, args = pool.conn.calls[-1]
    assert kind == "fetch"
    assert "date <= $4" in query
    assert args == ("000001", None, None, date(2026, 1, 2))


@pytest.mark.asyncio
async def test_pg_market_data_joins_adj_factor_and_returns_dual_adjusted_prices():
    pool = FakePool()
    store = PgCoreStore(pool)

    await store.get_market_data("000001", as_of_date=date(2026, 1, 2))

    _, query, _ = pool.conn.calls[-1]
    assert "LEFT JOIN adj_factor" in query
    assert "hfq_close" in query
    assert "qfq_close" in query


@pytest.mark.asyncio
async def test_pg_market_data_rejects_end_after_as_of():
    store = PgCoreStore(FakePool())

    with pytest.raises(LookAheadViolation):
        await store.get_market_data(
            "000001",
            end_date=date(2026, 1, 3),
            as_of_date=date(2026, 1, 2),
        )


@pytest.mark.asyncio
async def test_pg_market_data_rejects_start_after_end_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="start_date must be on or before end_date"):
        await store.get_market_data(
            "000001",
            start_date=date(2026, 1, 3),
            end_date=date(2026, 1, 2),
            as_of_date=date(2026, 1, 3),
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_market_data_rejects_empty_symbol_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="symbol is required"):
        await store.get_market_data(" ", as_of_date=date(2026, 1, 3))

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_financials_reject_empty_symbol_or_period_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="symbol is required"):
        await store.get_financials("", "2025Q4", as_of_date=date(2026, 1, 5))

    with pytest.raises(ValueError, match="period is required"):
        await store.get_financials("000001", " ", as_of_date=date(2026, 1, 5))

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_index_constituents_require_as_of_and_bind_pit_window():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(LookAheadViolation):
        await store.get_index_constituents("000300")

    await store.get_index_constituents("000300", as_of_date=date(2026, 1, 15))

    kind, query, args = pool.conn.calls[-1]
    assert kind == "fetch"
    assert "FROM index_constituents" in query
    assert "in_date <= $2" in query
    assert "(out_date IS NULL OR out_date > $2)" in query
    assert args == ("000300", date(2026, 1, 15))


@pytest.mark.asyncio
async def test_pg_active_stock_universe_requires_as_of_and_filters_pit_window():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(LookAheadViolation):
        await store.get_active_stock_universe()

    await store.get_active_stock_universe(as_of_date=date(2026, 1, 15))

    kind, query, args = pool.conn.calls[-1]
    assert kind == "fetch"
    assert "FROM stock_universe" in query
    assert "ipo_date <= $1" in query
    assert "(delist_date IS NULL OR delist_date > $1)" in query
    assert args == (date(2026, 1, 15),)


@pytest.mark.asyncio
async def test_pg_index_constituents_rejects_empty_index_code_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="index_code is required"):
        await store.get_index_constituents(" ", as_of_date=date(2026, 1, 15))

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_proposal_status_rejects_non_positive_id_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="proposal_id must be a positive integer"):
        await store.get_proposal_status(0)

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_review_proposal_updates_status():
    pool = FakePool()
    store = PgCoreStore(pool)

    await store.review_proposal(
        ProposalReview(1, ProposalStatus.APPROVED, reviewed_by="tester", reason="ok")
    )

    calls = [call for call in pool.conn.calls if call[0] == "fetchval"]
    assert calls
    assert calls[-1][2][0:3] == (1, "approved", "tester")


@pytest.mark.asyncio
async def test_pg_review_proposal_rejects_non_positive_id_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="proposal_id must be a positive integer"):
        await store.review_proposal(
            ProposalReview(0, ProposalStatus.APPROVED, reviewed_by="tester")
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_approve_proposal_promotes_only_approved(monkeypatch):
    pool = FakePool()
    store = PgCoreStore(pool)

    async def approved_fetchrow(query, *args):
        pool.conn.calls.append(("fetchrow", query, args))
        if "SELECT status FROM proposals" in query:
            return {"status": "approved"}
        return None

    monkeypatch.setattr(pool.conn, "fetchrow", approved_fetchrow)

    result = await store.approve_proposal(1, "risk_officer", "promote")

    assert result == {}
    calls = [call for call in pool.conn.calls if call[0] == "fetchval"]
    assert calls[-1][2] == (1, "promoted", "risk_officer")


@pytest.mark.asyncio
async def test_pg_approve_proposal_rejects_non_positive_id_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="proposal_id must be a positive integer"):
        await store.approve_proposal(0, "risk_officer", "promote")

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_backtest_result_upserts_report():
    pool = FakePool()
    store = PgCoreStore(pool)

    report = BacktestReport(
        backtest_result_id="abc",
        strategy_name="buy_and_hold",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        as_of_date=date(2026, 1, 2),
        parameters={"symbol": "000001"},
        fills=[],
        nav=[],
        orders=[
            {
                "order_id": "2026-01-01:000001:buy:0",
                "submitted_date": date(2026, 1, 1),
                "symbol": "000001",
                "side": "buy",
                "target_weight": 1.0,
                "status": "filled",
                "execution_date": date(2026, 1, 2),
                "quantity": 1000,
                "reason": "filled",
            }
        ],
    )
    result_id = await store.save_backtest_result(report)

    assert result_id == "abc"
    kind, query, args = pool.conn.calls[-1]
    assert kind == "fetchval"
    assert "INSERT INTO backtest_results" in query
    assert "orders" in query
    assert args[0] == "abc"


@pytest.mark.asyncio
async def test_pg_backtest_result_rejects_empty_id_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="backtest_result_id is required"):
        await store.get_backtest_result(" ")

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_backtest_result_rejects_empty_id_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)
    report = BacktestReport(
        backtest_result_id=" ",
        strategy_name="buy_and_hold",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        as_of_date=date(2026, 1, 2),
        parameters={},
        fills=[],
        nav=[],
        orders=[],
    )

    with pytest.raises(ValueError, match="backtest_result_id is required"):
        await store.save_backtest_result(report)

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_backtest_result_rejects_empty_strategy_name_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)
    report = BacktestReport(
        backtest_result_id="result-empty-strategy",
        strategy_name=" ",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        as_of_date=date(2026, 1, 2),
        parameters={},
        fills=[],
        nav=[],
        orders=[],
    )

    with pytest.raises(ValueError, match="strategy_name is required"):
        await store.save_backtest_result(report)

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_factor_values_upsert_and_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    count = await store.save_factor_values(
        [
            {
                "symbol": "000001",
                "date": date(2026, 1, 2),
                "factor_id": "momentum_1d",
                "version": 1,
                "value": 0.1,
                "calc_timestamp": date(2026, 1, 2),
            }
        ]
    )
    await store.get_factor_values(
        ["momentum_1d"],
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 2),
    )

    assert count == 1
    assert any(call[0] == "execute" and "INSERT INTO factor_values" in call[1] for call in pool.conn.calls)
    assert pool.conn.calls[-1][2] == (
        ["momentum_1d"],
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 2),
    )


@pytest.mark.asyncio
async def test_pg_factor_values_reject_start_after_end_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="start_date must be on or before end_date"):
        await store.get_factor_values(
            ["momentum_1d"],
            date(2026, 1, 3),
            date(2026, 1, 2),
            date(2026, 1, 3),
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_factor_values_rejects_empty_symbol_before_execute():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="symbol is required"):
        await store.save_factor_values(
            [
                {
                    "symbol": " ",
                    "date": date(2026, 1, 2),
                    "factor_id": "momentum_1d",
                    "version": 1,
                    "value": 0.1,
                    "calc_timestamp": date(2026, 1, 2),
                }
            ]
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_factor_values_rejects_empty_factor_id_before_execute():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="factor_id is required"):
        await store.save_factor_values(
            [
                {
                    "symbol": "000001",
                    "date": date(2026, 1, 2),
                    "factor_id": " ",
                    "version": 1,
                    "value": 0.1,
                    "calc_timestamp": date(2026, 1, 2),
                }
            ]
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_factor_values_rejects_non_positive_version_before_execute():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="version must be a positive integer"):
        await store.save_factor_values(
            [
                {
                    "symbol": "000001",
                    "date": date(2026, 1, 2),
                    "factor_id": "momentum_1d",
                    "version": 0,
                    "value": 0.1,
                    "calc_timestamp": date(2026, 1, 2),
                }
            ]
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_factor_values_rejects_non_finite_value_before_execute():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="value must be finite"):
        await store.save_factor_values(
            [
                {
                    "symbol": "000001",
                    "date": date(2026, 1, 2),
                    "factor_id": "momentum_1d",
                    "version": 1,
                    "value": float("inf"),
                    "calc_timestamp": date(2026, 1, 2),
                }
            ]
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_factor_values_rejects_invalid_date_before_execute():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="date must be a valid date"):
        await store.save_factor_values(
            [
                {
                    "symbol": "000001",
                    "date": "not-a-date",
                    "factor_id": "momentum_1d",
                    "version": 1,
                    "value": 0.1,
                    "calc_timestamp": date(2026, 1, 2),
                }
            ]
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_factor_values_rejects_invalid_calc_timestamp_before_execute():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="calc_timestamp must be a valid datetime"):
        await store.save_factor_values(
            [
                {
                    "symbol": "000001",
                    "date": date(2026, 1, 2),
                    "factor_id": "momentum_1d",
                    "version": 1,
                    "value": 0.1,
                    "calc_timestamp": "not-a-time",
                }
            ]
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_uploaded_doc_replaces_chunks():
    pool = FakePool()
    store = PgCoreStore(pool)
    document = ParsedDocument(
        filename="note.md",
        path="/tmp/note.md",
        sha256="abc",
        text="hello",
        uploaded_ts=datetime(2026, 1, 1),
    )

    result = await store.save_uploaded_doc(document, [DocumentChunk("abc", 0, "hello")])

    assert result == {"doc_id": 1, "sha256": "abc", "chunks": 1}
    assert any(call[0] == "execute" and "DELETE FROM doc_chunks" in call[1] for call in pool.conn.calls)
    assert any(call[0] == "execute" and "ON CONFLICT (doc_id, seq)" in call[1] for call in pool.conn.calls)
    assert any(call[0] == "fetchval" and "doc_type=EXCLUDED.doc_type" in call[1] for call in pool.conn.calls)


@pytest.mark.asyncio
async def test_pg_uploaded_doc_rejects_empty_sha256_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="sha256 is required"):
        await store.get_uploaded_doc(" ")

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_universe_node_upsert_uses_manual_audit_fields():
    pool = FakePool()
    store = PgCoreStore(pool)
    builder = UniverseBuilder()
    node = builder.add_node("concept.ai", "AI", "concept", "data_steward", date(2026, 1, 2))

    await store.save_universe_node(node)

    kind, query, args = pool.conn.calls[-1]
    assert kind == "fetchval"
    assert "INSERT INTO semantic_nodes" in query
    assert "created_by" in query
    assert "as_of_date" in query
    assert args == ("concept.ai", "AI", "concept", "data_steward", date(2026, 1, 2), "active")


@pytest.mark.asyncio
async def test_pg_universe_node_rejects_synonym_duplicate_label(monkeypatch):
    pool = FakePool()
    store = PgCoreStore(pool)

    async def existing_labels(query, *args):
        pool.conn.calls.append(("fetch", query, args))
        if "FROM semantic_nodes" in query:
            return [{"node_id": "concept.ai", "label": "AI 概念"}]
        return []

    monkeypatch.setattr(pool.conn, "fetch", existing_labels)
    builder = UniverseBuilder()
    node = builder.add_node("concept.ai_duplicate", "ai-概念", "concept", "data_steward", date(2026, 1, 2))

    with pytest.raises(ValueError, match="synonym duplicate node label"):
        await store.save_universe_node(node)

    assert not any(call[0] == "fetchval" and "INSERT INTO semantic_nodes" in call[1] for call in pool.conn.calls)


@pytest.mark.asyncio
async def test_pg_save_universe_node_rejects_empty_node_id_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="node_id is required"):
        await store.save_universe_node(
            {
                "node_id": " ",
                "label": "AI",
                "level": "concept",
                "created_by": "data_steward",
                "as_of_date": date(2026, 1, 1),
            }
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_universe_node_rejects_empty_label_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="label is required"):
        await store.save_universe_node(
            {
                "node_id": "concept.empty",
                "label": " ",
                "level": "concept",
                "created_by": "data_steward",
                "as_of_date": date(2026, 1, 1),
            }
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_universe_node_rejects_empty_level_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="level is required"):
        await store.save_universe_node(
            {
                "node_id": "concept.empty",
                "label": "Empty",
                "level": " ",
                "created_by": "data_steward",
                "as_of_date": date(2026, 1, 1),
            }
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_universe_node_rejects_empty_created_by_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="created_by is required"):
        await store.save_universe_node(
            {
                "node_id": "concept.empty",
                "label": "Empty",
                "level": "concept",
                "created_by": " ",
                "as_of_date": date(2026, 1, 1),
            }
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_universe_edge_lifecycle_and_asof_children_query():
    pool = FakePool()
    store = PgCoreStore(pool)
    builder = UniverseBuilder()
    builder.add_node("concept.ai", "AI", "concept", "data_steward", date(2026, 1, 1))
    builder.add_node("stock.000001", "Ping An", "stock", "data_steward", date(2026, 1, 1))
    edge = builder.add_edge("concept.ai", "stock.000001", "contains", "data_steward", date(2026, 1, 2))

    await store.save_universe_edge(edge)
    await store.verify_universe_edge(edge["edge_id"], verified_by="factor_researcher", as_of_date=date(2026, 1, 3))
    await store.retire_universe_edge(edge["edge_id"], retired_by="risk_officer", as_of_date=date(2026, 1, 6))
    await store.get_universe_children_as_of("concept.ai", as_of_date=date(2026, 1, 5))

    assert any(call[0] == "fetchval" and "INSERT INTO semantic_edges" in call[1] for call in pool.conn.calls)
    assert any(call[0] == "fetchrow" and "verified_by=$2" in call[1] for call in pool.conn.calls)
    assert any(call[0] == "fetchrow" and "retired_by=$2" in call[1] for call in pool.conn.calls)
    kind, query, args = pool.conn.calls[-1]
    assert kind == "fetch"
    assert "verified_as_of <= $2" in query
    assert "(valid_to IS NULL OR valid_to > $2)" in query
    assert args == ("concept.ai", date(2026, 1, 5))


@pytest.mark.asyncio
async def test_pg_save_universe_edge_rejects_non_positive_explicit_id_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="edge_id must be a positive integer"):
        await store.save_universe_edge(
            {
                "edge_id": 0,
                "parent_id": "concept.ai",
                "child_id": "stock.000001",
                "relation_type": "contains",
                "created_by": "data_steward",
                "as_of_date": date(2026, 1, 2),
            }
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_universe_edge_rejects_empty_parent_id_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="parent_id is required"):
        await store.save_universe_edge(
            {
                "parent_id": " ",
                "child_id": "stock.000001",
                "relation_type": "contains",
                "created_by": "data_steward",
                "as_of_date": date(2026, 1, 2),
            }
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_universe_edge_rejects_empty_child_id_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="child_id is required"):
        await store.save_universe_edge(
            {
                "parent_id": "concept.ai",
                "child_id": " ",
                "relation_type": "contains",
                "created_by": "data_steward",
                "as_of_date": date(2026, 1, 2),
            }
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_universe_edge_rejects_empty_relation_type_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="relation_type is required"):
        await store.save_universe_edge(
            {
                "parent_id": "concept.ai",
                "child_id": "stock.000001",
                "relation_type": " ",
                "created_by": "data_steward",
                "as_of_date": date(2026, 1, 2),
            }
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_universe_edge_rejects_empty_created_by_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="created_by is required"):
        await store.save_universe_edge(
            {
                "parent_id": "concept.ai",
                "child_id": "stock.000001",
                "relation_type": "contains",
                "created_by": " ",
                "as_of_date": date(2026, 1, 2),
            }
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_verify_universe_edge_rejects_non_positive_id_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="edge_id must be a positive integer"):
        await store.verify_universe_edge(0, verified_by="factor_researcher", as_of_date=date(2026, 1, 3))

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_verify_universe_edge_rejects_empty_verified_by_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="verified_by is required"):
        await store.verify_universe_edge(1, verified_by=" ", as_of_date=date(2026, 1, 3))

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_retire_universe_edge_rejects_non_positive_id_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="edge_id must be a positive integer"):
        await store.retire_universe_edge(0, retired_by="risk_officer", as_of_date=date(2026, 1, 4))

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_retire_universe_edge_rejects_empty_retired_by_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="retired_by is required"):
        await store.retire_universe_edge(1, retired_by="", as_of_date=date(2026, 1, 4))

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_universe_children_rejects_empty_parent_id_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="parent_id is required"):
        await store.get_universe_children_as_of(" ", as_of_date=date(2026, 1, 5))

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_semantic_node_search_uses_vector_or_label_and_asof_scope():
    pool = FakePool()
    store = PgCoreStore(pool)

    await store.search_semantic_nodes("AI", as_of_date=date(2026, 1, 5))

    kind, query, args = pool.conn.calls[-1]
    assert kind == "fetch"
    assert "FROM semantic_nodes" in query
    assert "as_of_date <= $2" in query
    assert "status = 'active'" in query
    assert "embedding <=> $3::vector" in query
    assert "label ILIKE" in query
    assert args[0:2] == ("AI", date(2026, 1, 5))


@pytest.mark.asyncio
async def test_pg_universe_edge_rejects_generic_parent_node(monkeypatch):
    pool = FakePool()
    store = PgCoreStore(pool)
    builder = UniverseBuilder()
    builder.add_node("concept.specific", "具体概念", "concept", "data_steward", date(2026, 1, 1))
    builder.add_node("stock.000001", "Ping An", "stock", "data_steward", date(2026, 1, 1))
    edge = builder.add_edge("concept.specific", "stock.000001", "contains", "data_steward", date(2026, 1, 2))
    edge["parent_id"] = "concept.generic"

    async def generic_parent(query, *args):
        pool.conn.calls.append(("fetchrow", query, args))
        if "FROM semantic_nodes" in query:
            return {"label": "概念", "level": "generic"}
        return None

    monkeypatch.setattr(pool.conn, "fetchrow", generic_parent)

    with pytest.raises(ValueError, match="parent node is too generic"):
        await store.save_universe_edge(edge)

    assert not any(call[0] == "fetchval" and "INSERT INTO semantic_edges" in call[1] for call in pool.conn.calls)


@pytest.mark.asyncio
async def test_pg_backtest_task_upsert_and_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    await store.save_backtest_task(
        {
            "task_id": "task-1",
            "status": "completed",
            "strategy_name": "buy_and_hold",
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 1, 2),
            "as_of_date": date(2026, 1, 2),
            "parameters": {"symbol": "000001"},
            "result": {"backtest_result_id": "abc"},
            "error": None,
        }
    )
    await store.get_backtest_task("task-1")

    upsert = pool.conn.calls[-2]
    query_call = pool.conn.calls[-1]
    assert upsert[0] == "fetchval"
    assert "INSERT INTO backtest_tasks" in upsert[1]
    assert "ON CONFLICT (task_id) DO UPDATE" in upsert[1]
    assert upsert[2][0:4] == ("task-1", "completed", "buy_and_hold", date(2026, 1, 1))
    assert query_call[0] == "fetchrow"
    assert "FROM backtest_tasks" in query_call[1]
    assert query_call[2] == ("task-1",)


@pytest.mark.asyncio
async def test_pg_backtest_task_rejects_empty_task_id_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="task_id is required"):
        await store.get_backtest_task(" ")

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_backtest_task_rejects_empty_task_id_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="task_id is required"):
        await store.save_backtest_task(
            {
                "task_id": " ",
                "status": "running",
                "strategy_name": "buy_and_hold",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 1, 2),
                "as_of_date": date(2026, 1, 2),
            }
        )

    assert pool.conn.calls == []


@pytest.mark.asyncio
async def test_pg_save_backtest_task_rejects_empty_status_before_query():
    pool = FakePool()
    store = PgCoreStore(pool)

    with pytest.raises(ValueError, match="status is required"):
        await store.save_backtest_task(
            {
                "task_id": "task-empty-status",
                "status": " ",
                "strategy_name": "buy_and_hold",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 1, 2),
                "as_of_date": date(2026, 1, 2),
            }
        )

    assert pool.conn.calls == []
