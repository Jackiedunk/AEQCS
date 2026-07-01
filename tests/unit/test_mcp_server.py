import base64
import asyncio
import logging
from datetime import date, datetime

import pytest

from aeqcs.core import mcp_server
from aeqcs.core.mcp_server import (
    build_mcp_server,
    configure_stdio_safety,
    normalize_asyncpg_dsn,
    page_items,
    resolve_mcp_runtime,
    tool_manifest,
)


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class FakeAsyncStore:
    def __init__(self) -> None:
        self.market_query: tuple | None = None
        self.index_constituents_query: tuple | None = None
        self.universe_children_query: tuple | None = None
        self.semantic_search_query: tuple | None = None
        self.proposals: list = []
        self.approve_called = False
        self.saved_backtest_tasks: list[dict] = []
        self.backtest_task_query: str | None = None
        self.backtest_result_query: str | None = None
        self.uploaded_doc_query: str | None = None

    async def get_market_data(self, symbol, start_date=None, end_date=None, as_of_date=None):
        self.market_query = (symbol, start_date, end_date, as_of_date)
        rows = [
            {
                "symbol": symbol,
                "date": date(2026, 1, 1),
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 11,
                "volume": 1000,
                "amount": 10000,
            },
            {
                "symbol": symbol,
                "date": date(2026, 1, 2),
                "open": 11,
                "high": 12,
                "low": 10,
                "close": 12,
                "volume": 1000,
                "amount": 11000,
            },
            {
                "symbol": symbol,
                "date": date(2026, 1, 3),
                "open": 12,
                "high": 13,
                "low": 11,
                "close": 13,
                "volume": 1000,
                "amount": 12000,
            },
        ]
        if start_date is not None:
            rows = [row for row in rows if row["date"] >= start_date]
        if end_date is not None:
            rows = [row for row in rows if row["date"] <= end_date]
        if as_of_date is not None:
            rows = [row for row in rows if row["date"] <= as_of_date]
        return rows

    async def get_financials(self, symbol, period, as_of_date=None):
        return {"symbol": symbol, "period": period, "roe": 0.12}

    async def get_index_constituents(self, index_code, as_of_date=None):
        self.index_constituents_query = (index_code, as_of_date)
        return [
            {"index_code": index_code, "symbol": "000001", "in_date": date(2026, 1, 1), "out_date": None},
            {"index_code": index_code, "symbol": "000002", "in_date": date(2026, 1, 5), "out_date": None},
        ]

    async def submit_proposal(self, proposal):
        self.proposals.append(proposal)
        return 42

    async def get_proposal_status(self, proposal_id):
        return {"proposal_id": proposal_id, "status": "pending"}

    async def review_proposal(self, review):
        return {"proposal_id": review.proposal_id, "status": review.status.value}

    async def approve_proposal(self, proposal_id, approver_id, decision):
        self.approve_called = True
        return {"proposal_id": proposal_id, "reviewed_by": approver_id, "status": "promoted", "decision": decision}

    async def save_backtest_result(self, report):
        return report.backtest_result_id

    async def get_backtest_result(self, backtest_result_id):
        self.backtest_result_query = backtest_result_id
        return {"backtest_result_id": backtest_result_id}

    async def save_backtest_task(self, task):
        self.saved_backtest_tasks.append(dict(task))
        return task["task_id"]

    async def get_backtest_task(self, task_id):
        self.backtest_task_query = task_id
        for task in reversed(self.saved_backtest_tasks):
            if task["task_id"] == task_id:
                return task
        return {}

    async def get_market_data_for_backtest(self):
        return [{"symbol": "000001", "date": date(2026, 1, 2), "close": 12}]

    async def save_factor_values(self, values):
        return len(values)

    async def get_factor_values(self, factor_ids, start_date, end_date, as_of_date):
        return [
            {"factor_id": factor_ids[0], "symbol": f"00000{i}", "value": i / 10}
            for i in range(5)
        ]

    async def save_uploaded_doc(self, document, chunks):
        return {"doc_id": 1, "sha256": document.sha256, "chunks": len(chunks)}

    async def get_uploaded_doc(self, sha256):
        self.uploaded_doc_query = sha256
        return {"sha256": sha256, "chunks": [{"seq": 0, "text": "x" * 200}]}

    async def load_daily(self):
        raise AssertionError("not used by this test")

    async def load_financials(self):
        raise AssertionError("not used by this test")

    async def save_universe_node(self, node):
        return node["node_id"]

    async def save_universe_edge(self, edge):
        return 1

    async def verify_universe_edge(self, edge_id, verified_by, as_of_date):
        return {"edge_id": edge_id, "verified": True, "verified_by": verified_by}

    async def retire_universe_edge(self, edge_id, retired_by, as_of_date):
        return {"edge_id": edge_id, "retired_by": retired_by}

    async def get_universe_children_as_of(self, parent_id, as_of_date):
        self.universe_children_query = (parent_id, as_of_date)
        return ["stock.000001", "stock.000002", "stock.000003"]

    async def search_semantic_nodes(self, query, as_of_date, query_embedding=None):
        self.semantic_search_query = (query, as_of_date, query_embedding)
        return [
            {
                "node_id": "concept.ai",
                "label": "AI 概念",
                "level": "concept",
                "as_of_date": date(2026, 1, 1),
                "status": "active",
                "score": 0.91,
            },
            {
                "node_id": "concept.robotics",
                "label": "机器人",
                "level": "concept",
                "as_of_date": date(2026, 1, 2),
                "status": "active",
                "score": 0.76,
            },
        ]


def persisted_running_backtest_task(task_id: str = "task-orphan") -> dict:
    return {
        "task_id": task_id,
        "backtest_result_id": task_id,
        "status": "running",
        "strategy_name": "buy_and_hold",
        "start_date": "2026-01-01",
        "end_date": "2026-01-02",
        "as_of_date": "2026-01-02",
        "parameters": {"symbol": "000001", "initial_cash": "10000"},
        "submitted_ts": "2026-01-02T00:00:00",
        "completed_ts": None,
        "result": None,
        "error": None,
    }


def persisted_running_pg_backtest_task(task_id: str = "task-orphan") -> dict:
    return {
        "task_id": task_id,
        "backtest_result_id": task_id,
        "status": "running",
        "strategy_name": "buy_and_hold",
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 1, 2),
        "as_of_date": date(2026, 1, 2),
        "parameters": {"symbol": "000001", "initial_cash": "10000"},
        "submitted_ts": datetime(2026, 1, 2),
        "completed_ts": None,
        "result": None,
        "error": None,
    }


class TypeCheckingBacktestStore(FakeAsyncStore):
    async def save_backtest_task(self, task):
        assert isinstance(task["start_date"], date)
        assert isinstance(task["end_date"], date)
        assert isinstance(task["as_of_date"], date)
        return await super().save_backtest_task(task)


@pytest.mark.asyncio
async def test_mcp_server_registers_manifest_tools(tmp_path):
    server = build_mcp_server(root=str(tmp_path))

    tools = await server.list_tools()

    assert [tool.name for tool in tools] == [tool["name"] for tool in tool_manifest()]


@pytest.mark.asyncio
async def test_mcp_server_scans_intraday_events(tmp_path):
    server = build_mcp_server(root=str(tmp_path))

    _content, structured = await server.call_tool(
        "scan_intraday_events",
        {
            "events": [
                {
                    "event_id": "m1",
                    "event_type": "market",
                    "symbol": "000001",
                    "close": 10.61,
                    "pre_close": 10.0,
                    "high_limit": 11.0,
                    "tick_status": "TRADE",
                }
            ]
        },
    )

    assert structured["items"][0]["rule_id"] == "sudden_spike"
    assert structured["items"][0]["action"] == "risk_officer.flag_spike"
    assert structured["count"] == 1
    assert structured["has_more"] is False


@pytest.mark.asyncio
async def test_mcp_server_scans_strategy_risks(tmp_path):
    server = build_mcp_server(root=str(tmp_path))

    manifest_names = [tool["name"] for tool in tool_manifest()]
    assert "scan_drawdown_risk" in manifest_names
    assert "scan_portfolio_risk" in manifest_names

    _content, drawdown = await server.call_tool(
        "scan_drawdown_risk",
        {
            "nav": [
                {"date": "2026-01-01", "nav": "100"},
                {"date": "2026-01-02", "nav": "88"},
            ],
            "warn_threshold": "0.05",
            "red_threshold": "0.10",
        },
    )
    _content, portfolio = await server.call_tool(
        "scan_portfolio_risk",
        {
            "cash": "0",
            "positions": {"000001": 80, "000002": 20},
            "prices": {"000001": "10", "000002": "10"},
            "max_gross_exposure": "0.80",
            "max_single_position_weight": "0.50",
        },
    )

    assert drawdown["status"] == "red"
    assert drawdown["alerts"][0]["action"] == "risk_officer.reduce_risk"
    assert portfolio["status"] == "red"
    assert [alert["action"] for alert in portfolio["alerts"]] == [
        "risk_officer.reduce_exposure",
        "risk_officer.review_concentration",
    ]


@pytest.mark.asyncio
async def test_mcp_server_calls_system_health(tmp_path):
    server = build_mcp_server(root=str(tmp_path))

    _content, structured = await server.call_tool("system_health", {})

    assert structured["status"] == "ok"
    assert structured["store"] == str(tmp_path)
    assert structured["backend"] == "local"
    assert "load_inbox" in structured["tools"]
    assert structured["resource_budget"]["embedding_resident_mb"] == 1024
    assert structured["resource_budget"]["within_limit"] is True
    assert structured["data_sources"]["baostock"] == {
        "roles": ["minute", "daily_cross_check"],
        "daily_quota": 50000,
        "concurrent": False,
        "health_check": "registered",
    }


@pytest.mark.asyncio
async def test_mcp_server_can_call_async_pg_style_store():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    _content, health = await server.call_tool("system_health", {})
    _content, structured = await server.call_tool(
        "get_market_data",
        {"symbol": "000001", "as_of_date": "2026-01-02"},
    )

    assert health["backend"] == "postgresql"
    assert health["resource_budget"]["embedding_resident_mb"] == 1024
    assert structured["items"][-1]["close"] == 12
    assert structured["count"] == 2
    assert store.market_query == ("000001", None, None, date(2026, 1, 2))


@pytest.mark.asyncio
async def test_mcp_get_market_data_supports_date_range_pagination():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    _content, structured = await server.call_tool(
        "get_market_data",
        {
            "symbol": "000001",
            "start_date": "2026-01-01",
            "end_date": "2026-01-03",
            "as_of_date": "2026-01-03",
            "limit": 1,
            "offset": 1,
        },
    )

    assert structured == {
        "items": [
            {
                "symbol": "000001",
                "date": "2026-01-02",
                "open": 11,
                "high": 12,
                "low": 10,
                "close": 12,
                "volume": 1000,
                "amount": 11000,
            }
        ],
        "count": 3,
        "offset": 1,
        "limit": 1,
        "has_more": True,
    }
    assert store.market_query == ("000001", date(2026, 1, 1), date(2026, 1, 3), date(2026, 1, 3))


@pytest.mark.asyncio
async def test_mcp_get_market_data_rejects_start_date_after_end_date_before_store_call():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    with pytest.raises(Exception, match="start_date must be on or before end_date"):
        await server.call_tool(
            "get_market_data",
            {
                "symbol": "000001",
                "start_date": "2026-01-03",
                "end_date": "2026-01-02",
                "as_of_date": "2026-01-03",
            },
        )

    assert store.market_query is None


@pytest.mark.asyncio
async def test_mcp_get_market_data_rejects_empty_symbol_before_store_call():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    with pytest.raises(Exception, match="symbol is required"):
        await server.call_tool(
            "get_market_data",
            {"symbol": " ", "as_of_date": "2026-01-03"},
        )

    assert store.market_query is None


@pytest.mark.asyncio
async def test_mcp_get_financials_rejects_empty_symbol_or_period_before_store_call():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    with pytest.raises(Exception, match="symbol is required"):
        await server.call_tool(
            "get_financials",
            {"symbol": "", "period": "2025Q4", "as_of_date": "2026-01-05"},
        )

    with pytest.raises(Exception, match="period is required"):
        await server.call_tool(
            "get_financials",
            {"symbol": "000001", "period": " ", "as_of_date": "2026-01-05"},
        )


@pytest.mark.asyncio
async def test_mcp_server_registers_approve_proposal_tool():
    server = build_mcp_server(async_store=FakeAsyncStore(), backend_name="postgresql")

    _content, structured = await server.call_tool(
        "approve_proposal",
        {"proposal_id": 7, "approver_id": "risk_officer", "decision": "promote"},
    )

    assert structured == {
        "proposal_id": 7,
        "reviewed_by": "risk_officer",
        "status": "promoted",
        "decision": "promote",
    }


@pytest.mark.asyncio
async def test_mcp_approve_proposal_rejects_unsupported_decision_before_store_call():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    with pytest.raises(Exception, match="unsupported approval decision"):
        await server.call_tool(
            "approve_proposal",
            {"proposal_id": 7, "approver_id": "risk_officer", "decision": "hold"},
        )

    assert store.approve_called is False


@pytest.mark.asyncio
async def test_mcp_submit_proposal_rejects_empty_source_before_store_call():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    with pytest.raises(Exception, match="source is required"):
        await server.call_tool(
            "submit_proposal",
            {
                "kind": "edge",
                "payload": {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
                "source": " ",
                "confidence": 0.8,
            },
        )

    assert store.proposals == []


@pytest.mark.asyncio
async def test_mcp_submit_proposal_rejects_empty_kind_before_store_call():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    with pytest.raises(Exception, match="kind is required"):
        await server.call_tool(
            "submit_proposal",
            {
                "kind": " ",
                "payload": {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
                "source": "test",
                "confidence": 0.8,
            },
        )

    assert store.proposals == []


@pytest.mark.asyncio
async def test_mcp_submit_proposal_rejects_invalid_snapshot_id_before_store_call():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    with pytest.raises(Exception, match="snapshot_id must be a positive integer"):
        await server.call_tool(
            "submit_proposal",
            {
                "kind": "edge",
                "payload": {"parent_id": "banking", "child_id": "000001", "relation_type": "contains"},
                "source": "test",
                "confidence": 0.8,
                "snapshot_id": 0,
            },
        )

    assert store.proposals == []


@pytest.mark.asyncio
async def test_mcp_server_registers_index_constituents_tool():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    _content, structured = await server.call_tool(
        "get_index_constituents",
        {"index_code": "000300", "as_of_date": "2026-01-15", "limit": 1, "offset": 1},
    )

    assert structured == {
        "items": [{"index_code": "000300", "symbol": "000002", "in_date": "2026-01-05", "out_date": None}],
        "count": 2,
        "offset": 1,
        "limit": 1,
        "has_more": False,
    }
    assert store.index_constituents_query == ("000300", date(2026, 1, 15))


@pytest.mark.asyncio
async def test_mcp_get_index_constituents_rejects_empty_index_code_before_store_call():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    with pytest.raises(Exception, match="index_code is required"):
        await server.call_tool(
            "get_index_constituents",
            {"index_code": " ", "as_of_date": "2026-01-15"},
        )

    assert store.index_constituents_query is None


def test_normalize_asyncpg_dsn_accepts_sqlalchemy_style_url():
    assert (
        normalize_asyncpg_dsn("postgresql+asyncpg://aeqcs_core:secret@localhost/aeqcs")
        == "postgresql://aeqcs_core:secret@localhost/aeqcs"
    )
    assert normalize_asyncpg_dsn("postgresql://user:secret@localhost/db") == "postgresql://user:secret@localhost/db"


def test_resolve_mcp_runtime_defaults_to_local():
    runtime = resolve_mcp_runtime({})

    assert runtime.backend == "local"
    assert runtime.local_root == "data/local"
    assert runtime.pg_dsn is None
    assert runtime.transport == "sse"
    assert runtime.host == "127.0.0.1"
    assert runtime.port == 8000


def test_resolve_mcp_runtime_selects_pg_backend():
    runtime = resolve_mcp_runtime(
        {
            "AEQCS_LOCAL_ROOT": "scratch/local",
            "AEQCS_CORE_PG_DSN": "postgresql+asyncpg://aeqcs_core:secret@localhost/aeqcs",
            "AEQCS_MCP_TRANSPORT": "stdio",
            "AEQCS_MCP_HOST": "127.0.0.1",
            "AEQCS_MCP_PORT": "8765",
        }
    )

    assert runtime.backend == "postgresql"
    assert runtime.local_root == "scratch/local"
    assert runtime.pg_dsn == "postgresql://aeqcs_core:secret@localhost/aeqcs"
    assert runtime.transport == "stdio"
    assert runtime.host == "127.0.0.1"
    assert runtime.port == 8765
    assert runtime.pool_size == 8


def test_resolve_mcp_runtime_allows_pool_size_override():
    runtime = resolve_mcp_runtime(
        {
            "AEQCS_CORE_PG_DSN": "postgresql://aeqcs_core:secret@localhost/aeqcs",
            "AEQCS_MCP_POOL_SIZE": "6",
        }
    )

    assert runtime.pool_size == 6


def test_resolve_mcp_runtime_rejects_pool_size_that_exceeds_connection_budget():
    with pytest.raises(ValueError, match="planned PostgreSQL connections exceed max_connections=20"):
        resolve_mcp_runtime(
            {
                "AEQCS_CORE_PG_DSN": "postgresql://aeqcs_core:secret@localhost/aeqcs",
                "AEQCS_MCP_POOL_SIZE": "12",
            }
        )


def test_resolve_mcp_runtime_rejects_non_loopback_host():
    with pytest.raises(ValueError, match="must bind to 127.0.0.1"):
        resolve_mcp_runtime({"AEQCS_MCP_HOST": "0.0.0.0"})


def test_page_items_rejects_serialized_responses_over_byte_budget():
    with pytest.raises(ValueError, match="response exceeds MCP byte budget"):
        page_items([{"payload": "x" * 200}], limit=1, offset=0, max_bytes=80)


@pytest.mark.asyncio
async def test_mcp_server_calls_load_inbox(tmp_path):
    server = build_mcp_server(root=str(tmp_path))

    _content, structured = await server.call_tool(
        "load_inbox",
        {
            "filename": "mcp-note.md",
            "content_base64": b64("factor: mcp_momentum = close / ref(close, 1) - 1"),
        },
    )

    assert structured["chunks"] == 1
    assert structured["proposal_ids"] == [1]


@pytest.mark.asyncio
async def test_mcp_tool_stdout_noise_is_redirected_to_stderr(monkeypatch, capsys, tmp_path):
    def noisy_call_local_tool(name, arguments, root="data/local"):
        print("accidental stdout noise")
        return {"name": name, "root": root}

    monkeypatch.setattr(mcp_server, "call_local_tool", noisy_call_local_tool)
    server = build_mcp_server(root=str(tmp_path))

    _content, structured = await server.call_tool("system_health", {})
    captured = capsys.readouterr()

    assert structured == {"name": "system_health", "root": str(tmp_path)}
    assert captured.out == ""
    assert "accidental stdout noise" in captured.err


def test_stdio_safety_configures_root_logging_to_stderr(capsys):
    configure_stdio_safety()

    logging.warning("stdio safety warning")
    captured = capsys.readouterr()

    assert "stdio safety warning" not in captured.out
    assert "stdio safety warning" in captured.err


@pytest.mark.asyncio
async def test_mcp_server_registers_universe_graph_tools():
    server = build_mcp_server(async_store=FakeAsyncStore(), backend_name="postgresql")

    _content, node = await server.call_tool(
        "create_universe_node",
        {
            "node_id": "concept.ai",
            "label": "AI",
            "level": "concept",
            "created_by": "data_steward",
            "as_of_date": "2026-01-01",
        },
    )
    _content, edge = await server.call_tool(
        "create_universe_edge",
        {
            "parent_id": "concept.ai",
            "child_id": "stock.000001",
            "relation_type": "contains",
            "created_by": "data_steward",
            "as_of_date": "2026-01-02",
        },
    )
    _content, children = await server.call_tool(
        "get_universe_children",
        {"parent_id": "concept.ai", "as_of_date": "2026-01-04"},
    )

    assert node["node_id"] == "concept.ai"
    assert edge["edge_id"] == 1
    assert children == {
        "items": ["stock.000001", "stock.000002", "stock.000003"],
        "count": 3,
        "offset": 0,
        "limit": 1000,
        "has_more": False,
    }


@pytest.mark.asyncio
async def test_mcp_get_universe_children_rejects_empty_parent_id_before_store_call():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    with pytest.raises(Exception, match="parent_id is required"):
        await server.call_tool(
            "get_universe_children",
            {"parent_id": " ", "as_of_date": "2026-01-05"},
        )

    assert store.universe_children_query is None


@pytest.mark.asyncio
async def test_mcp_server_registers_semantic_node_search_tool():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    _content, structured = await server.call_tool(
        "search_semantic_nodes",
        {"query": "AI", "as_of_date": "2026-01-05", "limit": 1, "offset": 1},
    )

    assert structured == {
        "items": [
            {
                "node_id": "concept.robotics",
                "label": "机器人",
                "level": "concept",
                "as_of_date": "2026-01-02",
                "status": "active",
                "score": 0.76,
            }
        ],
        "count": 2,
        "offset": 1,
        "limit": 1,
        "has_more": False,
    }
    assert store.semantic_search_query == ("AI", date(2026, 1, 5), None)


@pytest.mark.asyncio
async def test_mcp_list_tools_return_bounded_pages():
    server = build_mcp_server(async_store=FakeAsyncStore(), backend_name="postgresql")

    _content, factors = await server.call_tool(
        "get_factor_values",
        {
            "factor_ids": ["momentum_1d"],
            "start_date": "2026-01-01",
            "end_date": "2026-01-05",
            "as_of_date": "2026-01-05",
            "limit": 2,
            "offset": 1,
        },
    )
    _content, children = await server.call_tool(
        "get_universe_children",
        {"parent_id": "concept.ai", "as_of_date": "2026-01-05", "limit": 1, "offset": 2},
    )

    assert factors == {
        "items": [
            {"factor_id": "momentum_1d", "symbol": "000001", "value": 0.1},
            {"factor_id": "momentum_1d", "symbol": "000002", "value": 0.2},
        ],
        "count": 5,
        "offset": 1,
        "limit": 2,
        "has_more": True,
    }
    assert children == {
        "items": ["stock.000003"],
        "count": 3,
        "offset": 2,
        "limit": 1,
        "has_more": False,
    }


@pytest.mark.asyncio
async def test_mcp_list_tools_reject_invalid_pagination():
    server = build_mcp_server(async_store=FakeAsyncStore(), backend_name="postgresql")

    with pytest.raises(Exception, match="limit must be between 1 and 1000"):
        await server.call_tool(
            "get_universe_children",
            {"parent_id": "concept.ai", "as_of_date": "2026-01-05", "limit": 1001},
        )


@pytest.mark.asyncio
async def test_mcp_list_tools_reject_responses_over_byte_budget():
    server = build_mcp_server(async_store=FakeAsyncStore(), backend_name="postgresql")

    with pytest.raises(Exception, match="response exceeds MCP byte budget"):
        await server.call_tool(
            "get_market_data",
            {"symbol": "000001", "as_of_date": "2026-01-03", "max_bytes": 80},
        )


@pytest.mark.asyncio
async def test_mcp_non_list_tools_reject_responses_over_byte_budget():
    server = build_mcp_server(async_store=FakeAsyncStore(), backend_name="postgresql")

    with pytest.raises(Exception, match="response exceeds MCP byte budget"):
        await server.call_tool("get_uploaded_doc", {"sha256": "abc123", "max_bytes": 80})


@pytest.mark.asyncio
async def test_mcp_get_uploaded_doc_rejects_empty_sha256_before_store_call():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    with pytest.raises(Exception, match="sha256 is required"):
        await server.call_tool("get_uploaded_doc", {"sha256": " "})

    assert store.uploaded_doc_query is None


@pytest.mark.asyncio
async def test_mcp_backtest_task_status_rejects_response_over_byte_budget():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")
    _content, submitted = await server.call_tool(
        "submit_backtest_task",
        {
            "strategy_name": "buy_and_hold",
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
            "as_of_date": "2026-01-02",
            "parameters": {"symbol": "000001", "initial_cash": "10000"},
        },
    )

    with pytest.raises(Exception, match="response exceeds MCP byte budget"):
        await server.call_tool(
            "get_backtest_task",
            {"task_id": submitted["task_id"], "max_bytes": 80},
        )


@pytest.mark.asyncio
async def test_mcp_backtest_task_submission_and_status():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    _content, submitted = await server.call_tool(
        "submit_backtest_task",
        {
            "strategy_name": "buy_and_hold",
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
            "as_of_date": "2026-01-02",
            "parameters": {"symbol": "000001", "initial_cash": "10000"},
        },
    )
    _content, status = await server.call_tool("get_backtest_task", {"task_id": submitted["task_id"]})

    assert submitted["status"] in {"queued", "running", "completed"}
    assert submitted["task_id"]
    assert status["task_id"] == submitted["task_id"]
    assert status["status"] == "completed"
    assert status["result"]["backtest_result_id"]
    assert [task["status"] for task in store.saved_backtest_tasks] == ["queued", "running", "completed"]


@pytest.mark.asyncio
async def test_mcp_get_backtest_task_rejects_empty_task_id_before_store_call():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    with pytest.raises(Exception, match="task_id is required"):
        await server.call_tool("get_backtest_task", {"task_id": " "})

    assert store.backtest_task_query is None


@pytest.mark.asyncio
async def test_mcp_run_backtest_returns_pollable_running_result_id():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    _content, submitted = await server.call_tool(
        "run_backtest",
        {
            "strategy_name": "buy_and_hold",
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
            "as_of_date": "2026-01-02",
            "parameters": {"symbol": "000001", "initial_cash": "10000"},
        },
    )
    _content, running = await server.call_tool(
        "get_backtest_result",
        {"backtest_result_id": submitted["backtest_result_id"]},
    )
    await asyncio.sleep(0)
    _content, completed = await server.call_tool(
        "get_backtest_result",
        {"backtest_result_id": submitted["backtest_result_id"]},
    )

    assert submitted["status"] == "running"
    assert submitted["backtest_result_id"]
    assert running["backtest_result_id"] == submitted["backtest_result_id"]
    assert running["status"] in {"running", "completed"}
    assert completed["status"] == "completed"
    assert completed["result"]["backtest_result_id"]


@pytest.mark.asyncio
async def test_mcp_backtest_task_marks_orphaned_persisted_running_task_failed():
    store = FakeAsyncStore()
    store.saved_backtest_tasks.append(persisted_running_backtest_task())
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    _content, status = await server.call_tool("get_backtest_task", {"task_id": "task-orphan"})

    assert status["task_id"] == "task-orphan"
    assert status["status"] == "failed"
    assert "MCP process restart" in status["error"]
    assert store.saved_backtest_tasks[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_mcp_orphaned_backtest_recovery_preserves_pg_date_types():
    store = TypeCheckingBacktestStore()
    store.saved_backtest_tasks.append(persisted_running_pg_backtest_task())
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    _content, status = await server.call_tool("get_backtest_task", {"task_id": "task-orphan"})

    assert status["status"] == "failed"
    assert status["start_date"] == "2026-01-01"
    assert store.saved_backtest_tasks[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_mcp_backtest_result_marks_orphaned_persisted_running_task_failed():
    store = FakeAsyncStore()
    store.saved_backtest_tasks.append(persisted_running_backtest_task())
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    _content, result = await server.call_tool("get_backtest_result", {"backtest_result_id": "task-orphan"})

    assert result["backtest_result_id"] == "task-orphan"
    assert result["status"] == "failed"
    assert "MCP process restart" in result["error"]
    assert store.saved_backtest_tasks[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_mcp_get_backtest_result_rejects_empty_id_before_store_call():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    with pytest.raises(Exception, match="backtest_result_id is required"):
        await server.call_tool("get_backtest_result", {"backtest_result_id": " "})

    assert store.backtest_result_query is None


@pytest.mark.asyncio
async def test_mcp_run_backtest_rejects_missing_symbol_before_task_submission():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    with pytest.raises(Exception, match="parameters.symbol is required"):
        await server.call_tool(
            "run_backtest",
            {
                "strategy_name": "buy_and_hold",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "as_of_date": "2026-01-02",
                "parameters": {},
            },
        )

    assert store.saved_backtest_tasks == []


@pytest.mark.asyncio
async def test_mcp_backtest_rejects_invalid_request_before_task_submission():
    store = FakeAsyncStore()
    server = build_mcp_server(async_store=store, backend_name="postgresql")

    with pytest.raises(Exception, match="unsupported strategy"):
        await server.call_tool(
            "submit_backtest_task",
            {
                "strategy_name": "unknown_strategy",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "as_of_date": "2026-01-02",
                "parameters": {"symbol": "000001", "initial_cash": "10000"},
            },
        )
    with pytest.raises(Exception, match="after as_of"):
        await server.call_tool(
            "run_backtest",
            {
                "strategy_name": "buy_and_hold",
                "start_date": "2026-01-01",
                "end_date": "2026-01-05",
                "as_of_date": "2026-01-02",
                "parameters": {"symbol": "000001", "initial_cash": "10000"},
            },
        )

    assert store.saved_backtest_tasks == []
