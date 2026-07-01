"""MCP server boundary for the deterministic core."""

from __future__ import annotations

import os
import sys
import json
import logging
import asyncio
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import uuid4

import anyio
from mcp.server.fastmcp import FastMCP

from aeqcs.core.config import (
    load_yaml,
    load_settings,
    memory_resource_budget,
    validate_connection_budget,
    validate_memory_resource_budget,
)
from aeqcs.core.json import to_jsonable
from aeqcs.core.service import (
    AsyncCoreService,
    CoreService,
    validate_backtest_parameters,
)
from aeqcs.core.versioning import require_non_empty_text, require_valid_date_range
from aeqcs.core.versioning import assert_not_after
from aeqcs.store.pg_core import PgCoreStore
from aeqcs.store.local import LocalStore
from aeqcs.store.protocols import AsyncCoreStore


MCP_MAX_PAGE_LIMIT = 1000
MCP_MAX_RESPONSE_BYTES = 1_000_000


def configure_stdio_safety() -> None:
    """Keep stdout reserved for MCP JSON-RPC frames in stdio mode."""

    logging.basicConfig(level=os.environ.get("AEQCS_LOG_LEVEL", "INFO"), stream=sys.stderr, force=True)
    try:
        import structlog

        structlog.configure(
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
    except ImportError:
        return


def tool_manifest() -> list[dict[str, Any]]:
    return [
        {"name": "get_market_data", "requires_as_of": True},
        {"name": "get_financials", "requires_as_of": True},
        {"name": "get_index_constituents", "requires_as_of": True},
        {"name": "submit_proposal", "requires_as_of": False},
        {"name": "get_proposal_status", "requires_as_of": False},
        {"name": "review_proposal", "requires_as_of": False},
        {"name": "approve_proposal", "requires_as_of": False},
        {"name": "run_backtest", "requires_as_of": True},
        {"name": "get_backtest_result", "requires_as_of": False},
        {"name": "submit_backtest_task", "requires_as_of": True},
        {"name": "get_backtest_task", "requires_as_of": False},
        {"name": "compute_factors", "requires_as_of": True},
        {"name": "get_factor_values", "requires_as_of": True},
        {"name": "load_inbox", "requires_as_of": False},
        {"name": "get_uploaded_doc", "requires_as_of": False},
        {"name": "create_universe_node", "requires_as_of": True},
        {"name": "create_universe_edge", "requires_as_of": True},
        {"name": "verify_universe_edge", "requires_as_of": True},
        {"name": "retire_universe_edge", "requires_as_of": True},
        {"name": "get_universe_children", "requires_as_of": True},
        {"name": "search_semantic_nodes", "requires_as_of": True},
        {"name": "scan_intraday_events", "requires_as_of": False},
        {"name": "scan_drawdown_risk", "requires_as_of": False},
        {"name": "scan_portfolio_risk", "requires_as_of": False},
        {"name": "system_health", "requires_as_of": False},
    ]


def local_service(root: str = "data/local") -> CoreService:
    return CoreService(LocalStore(root))


@dataclass(frozen=True)
class McpRuntimeConfig:
    backend: str
    local_root: str
    pg_dsn: str | None = None
    transport: str = "sse"
    host: str = "127.0.0.1"
    port: int = 8000
    pool_size: int = 8


@dataclass
class BacktestTask:
    task_id: str
    status: str
    submitted_ts: datetime
    strategy_name: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    as_of_date: date | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    completed_ts: datetime | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "backtest_result_id": self.task_id,
            "status": self.status,
            "strategy_name": self.strategy_name,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "parameters": self.parameters,
            "submitted_ts": self.submitted_ts.isoformat(),
            "completed_ts": self.completed_ts.isoformat() if self.completed_ts else None,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class BacktestTaskRegistry:
    tasks: dict[str, BacktestTask] = field(default_factory=dict)

    def submit(
        self,
        strategy_name: str,
        start_date: date,
        end_date: date,
        parameters: dict[str, Any],
        as_of_date: date,
    ) -> BacktestTask:
        task = BacktestTask(
            task_id=uuid4().hex,
            status="queued",
            submitted_ts=datetime.utcnow(),
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            parameters=parameters,
            as_of_date=as_of_date,
        )
        self.tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if task is None:
            return {}
        return task.to_record()

    def mark_running(self, task_id: str) -> None:
        self.tasks[task_id].status = "running"

    def mark_completed(self, task_id: str, result: dict[str, Any]) -> None:
        task = self.tasks[task_id]
        task.status = "completed"
        task.result = result
        task.completed_ts = datetime.utcnow()

    def mark_failed(self, task_id: str, error: Exception) -> None:
        task = self.tasks[task_id]
        task.status = "failed"
        task.error = str(error)
        task.completed_ts = datetime.utcnow()


def normalize_asyncpg_dsn(dsn: str) -> str:
    """Convert SQLAlchemy asyncpg URLs into URLs accepted by asyncpg."""

    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


def resolve_mcp_runtime(env: dict[str, str] | os._Environ[str] = os.environ) -> McpRuntimeConfig:
    settings = load_settings()
    local_root = env.get("AEQCS_LOCAL_ROOT", "data/local")
    transport = env.get("AEQCS_MCP_TRANSPORT", "sse")
    if transport not in {"sse", "stdio"}:
        raise ValueError(f"unsupported MCP transport: {transport}")
    host = env.get("AEQCS_MCP_HOST", "127.0.0.1")
    if host != "127.0.0.1":
        raise ValueError("AEQCS MCP HTTP/SSE service must bind to 127.0.0.1")
    port = int(env.get("AEQCS_MCP_PORT", "8000"))
    pool_size = int(env.get("AEQCS_MCP_POOL_SIZE", settings["database"]["core"]["pool_size"]))
    budget_settings = {
        **settings,
        "database": {
            **settings["database"],
            "core": {
                **settings["database"]["core"],
                "pool_size": pool_size,
            },
        },
    }
    validate_connection_budget(budget_settings)
    validate_memory_resource_budget(settings)
    pg_dsn = env.get("AEQCS_CORE_PG_DSN") or env.get("AEQCS_PG_DSN") or env.get("AEQCS_CORE_DSN")
    if pg_dsn:
        return McpRuntimeConfig(
            backend="postgresql",
            local_root=local_root,
            pg_dsn=normalize_asyncpg_dsn(pg_dsn),
            transport=transport,
            host=host,
            port=port,
            pool_size=pool_size,
        )
    return McpRuntimeConfig(
        backend="local",
        local_root=local_root,
        transport=transport,
        host=host,
        port=port,
        pool_size=pool_size,
    )


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("date value must be an ISO date") from exc


def parse_optional_date(value: str | None, name: str = "date") -> date | None:
    if value in {None, ""}:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def required_argument(arguments: dict[str, Any], name: str) -> Any:
    if name not in arguments or arguments[name] is None:
        raise ValueError(f"{name} is required")
    return arguments[name]


def parse_argument_date(arguments: dict[str, Any], name: str) -> date:
    value = required_argument(arguments, name)
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


def parse_optional_date_range(
    start_value: str | None,
    end_value: str | None,
) -> tuple[date | None, date | None]:
    start_date = parse_optional_date(start_value, "start_date")
    end_date = parse_optional_date(end_value, "end_date")
    if start_date is not None and end_date is not None:
        require_valid_date_range(start_date, end_date)
    return start_date, end_date


def parse_argument_int(arguments: dict[str, Any], name: str) -> int:
    value = required_argument(arguments, name)
    try:
        parsed = int(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def call_local_tool(name: str, arguments: dict[str, Any], root: str = "data/local") -> Any:
    """Call a tool implementation without MCP transport.

    This keeps the deterministic contract testable before stdio wiring and
    PostgreSQL credentials are available.
    """

    service = local_service(root)
    if name == "get_market_data":
        symbol = require_non_empty_text(required_argument(arguments, "symbol"), "symbol")
        start_date, end_date = parse_optional_date_range(
            arguments.get("start_date"),
            arguments.get("end_date"),
        )
        return to_jsonable(
            service.store.get_market_data(
                symbol,
                start_date,
                end_date,
                parse_argument_date(arguments, "as_of_date"),
            )
        )
    if name == "get_financials":
        symbol = require_non_empty_text(required_argument(arguments, "symbol"), "symbol")
        period = require_non_empty_text(required_argument(arguments, "period"), "period")
        return to_jsonable(
            service.get_financials(
                symbol,
                period,
                parse_argument_date(arguments, "as_of_date"),
            )
        )
    if name == "get_index_constituents":
        index_code = require_non_empty_text(required_argument(arguments, "index_code"), "index_code")
        return to_jsonable(
            service.get_index_constituents(
                index_code,
                parse_argument_date(arguments, "as_of_date"),
            )
        )
    if name == "load_inbox":
        return to_jsonable(
            service.load_inbox(
                required_argument(arguments, "filename"),
                required_argument(arguments, "content_base64"),
                arguments.get("doc_type", "note"),
            )
        )
    if name == "get_uploaded_doc":
        sha256 = require_non_empty_text(required_argument(arguments, "sha256"), "sha256")
        return to_jsonable(service.get_uploaded_doc(sha256))
    if name == "compute_factors":
        return to_jsonable(
            service.compute_factors(
                required_argument(arguments, "factor_ids"),
                parse_argument_date(arguments, "start_date"),
                parse_argument_date(arguments, "end_date"),
                parse_argument_date(arguments, "as_of_date"),
            )
        )
    if name == "get_factor_values":
        return to_jsonable(
            service.get_factor_values(
                required_argument(arguments, "factor_ids"),
                parse_argument_date(arguments, "start_date"),
                parse_argument_date(arguments, "end_date"),
                parse_argument_date(arguments, "as_of_date"),
            )
        )
    if name == "run_backtest":
        return to_jsonable(
            service.run_backtest(
                required_argument(arguments, "strategy_name"),
                parse_argument_date(arguments, "start_date"),
                parse_argument_date(arguments, "end_date"),
                dict(arguments.get("parameters", {})),
                parse_argument_date(arguments, "as_of_date"),
            )
        )
    if name == "get_backtest_result":
        backtest_result_id = require_non_empty_text(
            required_argument(arguments, "backtest_result_id"),
            "backtest_result_id",
        )
        return to_jsonable(service.get_backtest_result(backtest_result_id))
    if name == "submit_proposal":
        return service.submit_proposal(
            required_argument(arguments, "kind"),
            required_argument(arguments, "payload"),
            required_argument(arguments, "source"),
            required_argument(arguments, "confidence"),
            arguments.get("snapshot_id"),
        )
    if name == "get_proposal_status":
        return to_jsonable(service.get_proposal_status(parse_argument_int(arguments, "proposal_id")))
    if name == "review_proposal":
        return to_jsonable(
            service.review_proposal(
                parse_argument_int(arguments, "proposal_id"),
                required_argument(arguments, "status"),
                required_argument(arguments, "reviewed_by"),
                arguments.get("reason", ""),
                arguments.get("backtest_result"),
            )
        )
    if name == "approve_proposal":
        return to_jsonable(
            service.approve_proposal(
                parse_argument_int(arguments, "proposal_id"),
                required_argument(arguments, "approver_id"),
                required_argument(arguments, "decision"),
            )
        )
    if name == "create_universe_node":
        return to_jsonable(
            service.create_universe_node(
                required_argument(arguments, "node_id"),
                required_argument(arguments, "label"),
                required_argument(arguments, "level"),
                required_argument(arguments, "created_by"),
                parse_argument_date(arguments, "as_of_date"),
            )
        )
    if name == "create_universe_edge":
        return to_jsonable(
            service.create_universe_edge(
                required_argument(arguments, "parent_id"),
                required_argument(arguments, "child_id"),
                required_argument(arguments, "relation_type"),
                required_argument(arguments, "created_by"),
                parse_argument_date(arguments, "as_of_date"),
            )
        )
    if name == "verify_universe_edge":
        return to_jsonable(
            service.verify_universe_edge(
                parse_argument_int(arguments, "edge_id"),
                required_argument(arguments, "verified_by"),
                parse_argument_date(arguments, "as_of_date"),
            )
        )
    if name == "retire_universe_edge":
        return to_jsonable(
            service.retire_universe_edge(
                parse_argument_int(arguments, "edge_id"),
                required_argument(arguments, "retired_by"),
                parse_argument_date(arguments, "as_of_date"),
            )
        )
    if name == "get_universe_children":
        parent_id = require_non_empty_text(required_argument(arguments, "parent_id"), "parent_id")
        return to_jsonable(
            service.get_universe_children(
                parent_id,
                parse_argument_date(arguments, "as_of_date"),
            )
        )
    if name == "search_semantic_nodes":
        return to_jsonable(
            service.search_semantic_nodes(
                required_argument(arguments, "query"),
                parse_argument_date(arguments, "as_of_date"),
                arguments.get("query_embedding"),
            )
        )
    if name == "scan_intraday_events":
        return to_jsonable(service.scan_intraday_events(list(required_argument(arguments, "events"))))
    if name == "scan_drawdown_risk":
        return to_jsonable(
            service.scan_drawdown_risk(
                required_argument(arguments, "nav"),
                arguments.get("warn_threshold", "0.05"),
                arguments.get("red_threshold", "0.10"),
            )
        )
    if name == "scan_portfolio_risk":
        return to_jsonable(
            service.scan_portfolio_risk(
                cash=required_argument(arguments, "cash"),
                positions=required_argument(arguments, "positions"),
                prices=required_argument(arguments, "prices"),
                max_gross_exposure=arguments.get("max_gross_exposure", "1"),
                max_single_position_weight=arguments.get("max_single_position_weight", "0.30"),
            )
        )
    if name == "system_health":
        return _health_payload(root, "local")
    raise ValueError(f"unsupported local tool: {name}")


def _root(default: str) -> str:
    return os.environ.get("AEQCS_LOCAL_ROOT", default)


def _call_tool_safely(name: str, arguments: dict[str, Any], root: str) -> Any:
    with redirect_stdout(sys.stderr):
        return call_local_tool(name, arguments, root=root)


def _health_payload(store: str, backend: str) -> dict[str, Any]:
    settings = load_settings()
    data_sources = load_yaml("aeqcs/config/data_sources.yaml")
    baostock_limits = data_sources.get("rate_limits", {}).get("baostock", {})
    return {
        "status": "ok",
        "store": store,
        "backend": backend,
        "tools": [tool["name"] for tool in tool_manifest()],
        "resource_budget": memory_resource_budget(settings),
        "data_sources": {
            "baostock": {
                "roles": [
                    role
                    for role, source in data_sources.get("sources", {}).items()
                    if source == "baostock"
                ],
                "daily_quota": baostock_limits.get("daily_quota"),
                "concurrent": baostock_limits.get("concurrent"),
                "health_check": "registered",
            }
        },
    }


def page_items(
    items: list[Any],
    limit: int = MCP_MAX_PAGE_LIMIT,
    offset: int = 0,
    max_bytes: int = MCP_MAX_RESPONSE_BYTES,
) -> dict[str, Any]:
    if limit < 1 or limit > MCP_MAX_PAGE_LIMIT:
        raise ValueError(f"limit must be between 1 and {MCP_MAX_PAGE_LIMIT}")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0")
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    count = len(items)
    end = offset + limit
    payload = {
        "items": items[offset:end],
        "count": count,
        "offset": offset,
        "limit": limit,
        "has_more": end < count,
    }
    return budget_json_response(payload, max_bytes=max_bytes)


def budget_json_response(payload: dict[str, Any], max_bytes: int = MCP_MAX_RESPONSE_BYTES) -> dict[str, Any]:
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    response_bytes = len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))
    if response_bytes > max_bytes:
        raise ValueError(
            f"response exceeds MCP byte budget: {response_bytes} > {max_bytes}; "
            "lower limit or increase max_bytes"
        )
    return payload


async def persist_backtest_task(async_store: AsyncCoreStore | None, task: BacktestTask) -> None:
    if async_store is None:
        return
    await async_store.save_backtest_task(task.to_record())


async def recover_orphaned_backtest_task(
    async_store: AsyncCoreStore,
    task: dict[str, Any],
) -> dict[str, Any]:
    if task.get("status") not in {"queued", "running"}:
        return task
    recovered = {
        **task,
        "status": "failed",
        "completed_ts": datetime.utcnow().isoformat(),
        "error": "task recovered as failed after MCP process restart; resubmit backtest",
    }
    await async_store.save_backtest_task(recovered)
    return recovered


def validate_backtest_request(
    strategy_name: str,
    start_date: str,
    end_date: str,
    parameters: dict[str, Any],
    as_of_date: str,
) -> tuple[date, date, date]:
    if strategy_name != "buy_and_hold":
        raise ValueError(f"unsupported strategy: {strategy_name}")
    parsed_start_date = parse_date(start_date)
    parsed_end_date = parse_date(end_date)
    parsed_as_of_date = parse_date(as_of_date)
    assert_not_after(parsed_end_date, parsed_as_of_date)
    validate_backtest_parameters(parameters)
    return parsed_start_date, parsed_end_date, parsed_as_of_date


def build_mcp_server(
    root: str = "data/local",
    async_store: AsyncCoreStore | None = None,
    backend_name: str = "local",
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    async_service = AsyncCoreService(async_store) if async_store is not None else None
    backtest_tasks = BacktestTaskRegistry()
    server = FastMCP(
        "aeqcs-core",
        instructions=(
            "AEQCS deterministic core tools. All time-sensitive market and "
            "factor queries require an explicit as_of_date."
        ),
        host=host,
        port=port,
    )

    async def _execute_backtest_task(
        task: BacktestTask,
        strategy_name: str,
        start_date: str,
        end_date: str,
        parameters: dict[str, Any],
        as_of_date: str,
        mark_running: bool = True,
    ) -> None:
        parsed_start_date = parse_date(start_date)
        parsed_end_date = parse_date(end_date)
        parsed_as_of_date = parse_date(as_of_date)
        try:
            if mark_running:
                backtest_tasks.mark_running(task.task_id)
                await persist_backtest_task(async_store, backtest_tasks.tasks[task.task_id])
            if async_service is not None:
                result = await async_service.run_backtest(
                    strategy_name,
                    parsed_start_date,
                    parsed_end_date,
                    parameters,
                    parsed_as_of_date,
                )
            else:
                result = await anyio.to_thread.run_sync(
                    _call_tool_safely,
                    "run_backtest",
                    {
                        "strategy_name": strategy_name,
                        "start_date": start_date,
                        "end_date": end_date,
                        "parameters": parameters,
                        "as_of_date": as_of_date,
                    },
                    _root(root),
                )
            backtest_tasks.mark_completed(task.task_id, to_jsonable(result))
            await persist_backtest_task(async_store, backtest_tasks.tasks[task.task_id])
        except Exception as exc:
            backtest_tasks.mark_failed(task.task_id, exc)
            await persist_backtest_task(async_store, backtest_tasks.tasks[task.task_id])

    async def _submit_backtest_background_task(
        strategy_name: str,
        start_date: str,
        end_date: str,
        parameters: dict[str, Any],
        as_of_date: str,
        start_running: bool = False,
    ) -> BacktestTask:
        parsed_start_date, parsed_end_date, parsed_as_of_date = validate_backtest_request(
            strategy_name,
            start_date,
            end_date,
            parameters,
            as_of_date,
        )
        task = backtest_tasks.submit(
            strategy_name,
            parsed_start_date,
            parsed_end_date,
            parameters,
            parsed_as_of_date,
        )
        if start_running:
            backtest_tasks.mark_running(task.task_id)
        await persist_backtest_task(async_store, task)
        asyncio.create_task(
            _execute_backtest_task(
                task,
                strategy_name,
                start_date,
                end_date,
                parameters,
                as_of_date,
                mark_running=not start_running,
            )
        )
        return task

    @server.tool(description="Get market rows for a symbol with explicit as-of and pagination.")
    async def get_market_data(
        symbol: str,
        as_of_date: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = MCP_MAX_PAGE_LIMIT,
        offset: int = 0,
        max_bytes: int = MCP_MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        symbol = require_non_empty_text(symbol, "symbol")
        parsed_start_date, parsed_end_date = parse_optional_date_range(start_date, end_date)
        parsed_as_of_date = parse_date(as_of_date)
        if async_store is not None:
            rows = await async_store.get_market_data(
                symbol,
                parsed_start_date,
                parsed_end_date,
                parsed_as_of_date,
            )
        else:
            rows = _call_tool_safely(
                "get_market_data",
                {
                    "symbol": symbol,
                    "start_date": parsed_start_date.isoformat() if parsed_start_date else None,
                    "end_date": parsed_end_date.isoformat() if parsed_end_date else None,
                    "as_of_date": as_of_date,
                },
                root=_root(root),
            )
        return page_items(to_jsonable(rows), limit=limit, offset=offset, max_bytes=max_bytes)

    @server.tool(description="Get point-in-time financial indicators for a symbol and period.")
    async def get_financials(symbol: str, period: str, as_of_date: str) -> dict[str, Any]:
        symbol = require_non_empty_text(symbol, "symbol")
        period = require_non_empty_text(period, "period")
        if async_service is not None:
            return to_jsonable(await async_service.get_financials(symbol, period, parse_date(as_of_date)))
        return _call_tool_safely(
            "get_financials",
            {"symbol": symbol, "period": period, "as_of_date": as_of_date},
            root=_root(root),
        )

    @server.tool(description="Get index constituents active at an explicit as-of date.")
    async def get_index_constituents(
        index_code: str,
        as_of_date: str,
        limit: int = MCP_MAX_PAGE_LIMIT,
        offset: int = 0,
        max_bytes: int = MCP_MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        index_code = require_non_empty_text(index_code, "index_code")
        if async_service is not None:
            return page_items(
                to_jsonable(await async_service.get_index_constituents(index_code, parse_date(as_of_date))),
                limit=limit,
                offset=offset,
                max_bytes=max_bytes,
            )
        return page_items(
            _call_tool_safely(
                "get_index_constituents",
                {"index_code": index_code, "as_of_date": as_of_date},
                root=_root(root),
            ),
            limit=limit,
            offset=offset,
            max_bytes=max_bytes,
        )

    @server.tool(description="Submit a proposed factor, correction, or strategy change to the gate.")
    async def submit_proposal(
        kind: str,
        payload: dict[str, Any],
        source: str,
        confidence: float,
        snapshot_id: int | None = None,
    ) -> int:
        if async_service is not None:
            return await async_service.submit_proposal(kind, payload, source, confidence, snapshot_id)
        return _call_tool_safely(
            "submit_proposal",
            {
                "kind": kind,
                "payload": payload,
                "source": source,
                "confidence": confidence,
                "snapshot_id": snapshot_id,
            },
            root=_root(root),
    )

    @server.tool(description="Get the gate status for a proposal.")
    async def get_proposal_status(proposal_id: int) -> dict[str, Any]:
        if async_service is not None:
            return to_jsonable(await async_service.get_proposal_status(proposal_id))
        return _call_tool_safely("get_proposal_status", {"proposal_id": proposal_id}, root=_root(root))

    @server.tool(description="Review a proposal and advance it through the gate state machine.")
    async def review_proposal(
        proposal_id: int,
        status: str,
        reviewed_by: str,
        reason: str = "",
        backtest_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if async_service is not None:
            return to_jsonable(
                await async_service.review_proposal(
                    proposal_id,
                    status,
                    reviewed_by,
                    reason,
                    backtest_result,
                )
            )
        return _call_tool_safely(
            "review_proposal",
            {
                "proposal_id": proposal_id,
                "status": status,
                "reviewed_by": reviewed_by,
                "reason": reason,
                "backtest_result": backtest_result,
            },
            root=_root(root),
        )

    @server.tool(description="Promote an approved proposal through the audited approval boundary.")
    async def approve_proposal(proposal_id: int, approver_id: str, decision: str) -> dict[str, Any]:
        if async_service is not None:
            return to_jsonable(await async_service.approve_proposal(proposal_id, approver_id, decision))
        return _call_tool_safely(
            "approve_proposal",
            {"proposal_id": proposal_id, "approver_id": approver_id, "decision": decision},
            root=_root(root),
        )

    @server.tool(description="Run a deterministic daily backtest with explicit as-of protection.")
    async def run_backtest(
        strategy_name: str,
        start_date: str,
        end_date: str,
        parameters: dict[str, Any],
        as_of_date: str,
    ) -> dict[str, Any]:
        task = await _submit_backtest_background_task(
            strategy_name,
            start_date,
            end_date,
            parameters,
            as_of_date,
            start_running=True,
        )
        record = task.to_record()
        return {"backtest_result_id": record["backtest_result_id"], "status": record["status"]}

    @server.tool(description="Get a persisted backtest report by id.")
    async def get_backtest_result(
        backtest_result_id: str,
        max_bytes: int = MCP_MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        backtest_result_id = require_non_empty_text(backtest_result_id, "backtest_result_id")
        task = backtest_tasks.get(backtest_result_id)
        if task:
            return budget_json_response(task, max_bytes=max_bytes)
        if async_store is not None:
            task = await async_store.get_backtest_task(backtest_result_id)
            if task:
                recovered_task = await recover_orphaned_backtest_task(async_store, task)
                return budget_json_response(to_jsonable(recovered_task), max_bytes=max_bytes)
        if async_service is not None:
            return budget_json_response(
                to_jsonable(await async_service.get_backtest_result(backtest_result_id)),
                max_bytes=max_bytes,
            )
        result = _call_tool_safely(
            "get_backtest_result",
            {"backtest_result_id": backtest_result_id},
            root=_root(root),
        )
        return budget_json_response(
            result,
            max_bytes=max_bytes,
        )

    @server.tool(description="Submit a deterministic backtest as an MCP background task.")
    async def submit_backtest_task(
        strategy_name: str,
        start_date: str,
        end_date: str,
        parameters: dict[str, Any],
        as_of_date: str,
    ) -> dict[str, Any]:
        task = await _submit_backtest_background_task(
            strategy_name,
            start_date,
            end_date,
            parameters,
            as_of_date,
        )
        return task.to_record()

    @server.tool(description="Get MCP background backtest task status by id.")
    async def get_backtest_task(
        task_id: str,
        max_bytes: int = MCP_MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        task_id = require_non_empty_text(task_id, "task_id")
        await asyncio.sleep(0)
        task = backtest_tasks.get(task_id)
        if task:
            return budget_json_response(task, max_bytes=max_bytes)
        if async_store is not None:
            task = await async_store.get_backtest_task(task_id)
            if task:
                task = await recover_orphaned_backtest_task(async_store, task)
            return budget_json_response(to_jsonable(task), max_bytes=max_bytes)
        return budget_json_response({}, max_bytes=max_bytes)

    @server.tool(description="Compute supported deterministic factors and persist the values.")
    async def compute_factors(
        factor_ids: list[str],
        start_date: str,
        end_date: str,
        as_of_date: str,
        limit: int = MCP_MAX_PAGE_LIMIT,
        offset: int = 0,
        max_bytes: int = MCP_MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        if async_service is not None:
            return page_items(
                to_jsonable(
                    await async_service.compute_factors(
                        factor_ids,
                        parse_date(start_date),
                        parse_date(end_date),
                        parse_date(as_of_date),
                    )
                ),
                limit=limit,
                offset=offset,
                max_bytes=max_bytes,
            )
        return page_items(
            _call_tool_safely(
                "compute_factors",
                {
                    "factor_ids": factor_ids,
                    "start_date": start_date,
                    "end_date": end_date,
                    "as_of_date": as_of_date,
                },
                root=_root(root),
            ),
            limit=limit,
            offset=offset,
            max_bytes=max_bytes,
        )

    @server.tool(description="Query persisted factor values with explicit as-of protection.")
    async def get_factor_values(
        factor_ids: list[str],
        start_date: str,
        end_date: str,
        as_of_date: str,
        limit: int = MCP_MAX_PAGE_LIMIT,
        offset: int = 0,
        max_bytes: int = MCP_MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        if async_service is not None:
            return page_items(
                to_jsonable(
                    await async_service.get_factor_values(
                        factor_ids,
                        parse_date(start_date),
                        parse_date(end_date),
                        parse_date(as_of_date),
                    )
                ),
                limit=limit,
                offset=offset,
                max_bytes=max_bytes,
            )
        return page_items(
            _call_tool_safely(
                "get_factor_values",
                {
                    "factor_ids": factor_ids,
                    "start_date": start_date,
                    "end_date": end_date,
                    "as_of_date": as_of_date,
                },
                root=_root(root),
            ),
            limit=limit,
            offset=offset,
            max_bytes=max_bytes,
        )

    @server.tool(description="Upload a text or Markdown document into the local inbox.")
    async def load_inbox(filename: str, content_base64: str, doc_type: str = "note") -> dict[str, Any]:
        if async_service is not None:
            return to_jsonable(await async_service.load_inbox(filename, content_base64, doc_type))
        return _call_tool_safely(
            "load_inbox",
            {"filename": filename, "content_base64": content_base64, "doc_type": doc_type},
            root=_root(root),
    )

    @server.tool(description="Get an uploaded document and its chunks by sha256.")
    async def get_uploaded_doc(
        sha256: str,
        max_bytes: int = MCP_MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        sha256 = require_non_empty_text(sha256, "sha256")
        if async_service is not None:
            return budget_json_response(
                to_jsonable(await async_service.get_uploaded_doc(sha256)),
                max_bytes=max_bytes,
            )
        return budget_json_response(
            _call_tool_safely("get_uploaded_doc", {"sha256": sha256}, root=_root(root)),
            max_bytes=max_bytes,
        )

    @server.tool(description="Create or update a manually audited universe graph node.")
    async def create_universe_node(
        node_id: str,
        label: str,
        level: str,
        created_by: str,
        as_of_date: str,
    ) -> dict[str, Any]:
        if async_service is not None:
            return to_jsonable(
                await async_service.create_universe_node(
                    node_id,
                    label,
                    level,
                    created_by,
                    parse_date(as_of_date),
                )
            )
        return _call_tool_safely(
            "create_universe_node",
            {
                "node_id": node_id,
                "label": label,
                "level": level,
                "created_by": created_by,
                "as_of_date": as_of_date,
            },
            root=_root(root),
        )

    @server.tool(description="Create a manually audited universe graph edge.")
    async def create_universe_edge(
        parent_id: str,
        child_id: str,
        relation_type: str,
        created_by: str,
        as_of_date: str,
    ) -> dict[str, Any]:
        if async_service is not None:
            return to_jsonable(
                await async_service.create_universe_edge(
                    parent_id,
                    child_id,
                    relation_type,
                    created_by,
                    parse_date(as_of_date),
                )
            )
        return _call_tool_safely(
            "create_universe_edge",
            {
                "parent_id": parent_id,
                "child_id": child_id,
                "relation_type": relation_type,
                "created_by": created_by,
                "as_of_date": as_of_date,
            },
            root=_root(root),
        )

    @server.tool(description="Mark a universe graph edge as verified by an audited role.")
    async def verify_universe_edge(edge_id: int, verified_by: str, as_of_date: str) -> dict[str, Any]:
        if async_service is not None:
            return to_jsonable(await async_service.verify_universe_edge(edge_id, verified_by, parse_date(as_of_date)))
        return _call_tool_safely(
            "verify_universe_edge",
            {"edge_id": edge_id, "verified_by": verified_by, "as_of_date": as_of_date},
            root=_root(root),
        )

    @server.tool(description="Retire a universe graph edge from a specific as-of date.")
    async def retire_universe_edge(edge_id: int, retired_by: str, as_of_date: str) -> dict[str, Any]:
        if async_service is not None:
            return to_jsonable(await async_service.retire_universe_edge(edge_id, retired_by, parse_date(as_of_date)))
        return _call_tool_safely(
            "retire_universe_edge",
            {"edge_id": edge_id, "retired_by": retired_by, "as_of_date": as_of_date},
            root=_root(root),
        )

    @server.tool(description="Return verified universe graph children visible at an explicit as-of date.")
    async def get_universe_children(
        parent_id: str,
        as_of_date: str,
        limit: int = MCP_MAX_PAGE_LIMIT,
        offset: int = 0,
        max_bytes: int = MCP_MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        parent_id = require_non_empty_text(parent_id, "parent_id")
        if async_service is not None:
            return page_items(
                await async_service.get_universe_children(parent_id, parse_date(as_of_date)),
                limit=limit,
                offset=offset,
                max_bytes=max_bytes,
            )
        return page_items(
            _call_tool_safely(
                "get_universe_children",
                {"parent_id": parent_id, "as_of_date": as_of_date},
                root=_root(root),
            ),
            limit=limit,
            offset=offset,
            max_bytes=max_bytes,
        )

    @server.tool(description="Search audited semantic nodes by text or caller-supplied embedding vector.")
    async def search_semantic_nodes(
        query: str,
        as_of_date: str,
        query_embedding: list[float] | None = None,
        limit: int = MCP_MAX_PAGE_LIMIT,
        offset: int = 0,
        max_bytes: int = MCP_MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        if async_service is not None:
            rows = await async_service.search_semantic_nodes(query, parse_date(as_of_date), query_embedding)
        else:
            rows = _call_tool_safely(
                "search_semantic_nodes",
                {
                    "query": query,
                    "as_of_date": as_of_date,
                    "query_embedding": query_embedding,
                },
                root=_root(root),
            )
        return page_items(to_jsonable(rows), limit=limit, offset=offset, max_bytes=max_bytes)

    @server.tool(description="Scan structured intraday events with deterministic CEP rules.")
    async def scan_intraday_events(
        events: list[dict[str, Any]],
        limit: int = MCP_MAX_PAGE_LIMIT,
        offset: int = 0,
        max_bytes: int = MCP_MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        if async_service is not None:
            alerts = to_jsonable(await async_service.scan_intraday_events(events))
        else:
            alerts = _call_tool_safely("scan_intraday_events", {"events": events}, root=_root(root))
        return page_items(alerts, limit=limit, offset=offset, max_bytes=max_bytes)

    @server.tool(description="Scan a NAV series for deterministic drawdown risk alerts.")
    async def scan_drawdown_risk(
        nav: list[dict[str, Any]],
        warn_threshold: str = "0.05",
        red_threshold: str = "0.10",
    ) -> dict[str, Any]:
        if async_service is not None:
            return to_jsonable(
                await async_service.scan_drawdown_risk(
                    nav,
                    warn_threshold=warn_threshold,
                    red_threshold=red_threshold,
                )
            )
        return _call_tool_safely(
            "scan_drawdown_risk",
            {
                "nav": nav,
                "warn_threshold": warn_threshold,
                "red_threshold": red_threshold,
            },
            root=_root(root),
        )

    @server.tool(description="Scan portfolio exposure and concentration for deterministic risk alerts.")
    async def scan_portfolio_risk(
        cash: str,
        positions: dict[str, Any],
        prices: dict[str, Any],
        max_gross_exposure: str = "1",
        max_single_position_weight: str = "0.30",
    ) -> dict[str, Any]:
        arguments = {
            "cash": cash,
            "positions": positions,
            "prices": prices,
            "max_gross_exposure": max_gross_exposure,
            "max_single_position_weight": max_single_position_weight,
        }
        if async_service is not None:
            return to_jsonable(
                await async_service.scan_portfolio_risk(
                    cash=cash,
                    positions=positions,
                    prices=prices,
                    max_gross_exposure=max_gross_exposure,
                    max_single_position_weight=max_single_position_weight,
                )
            )
        return _call_tool_safely("scan_portfolio_risk", arguments, root=_root(root))

    @server.tool(description="Return AEQCS core health and registered tool names.")
    async def system_health() -> dict[str, Any]:
        if async_service is not None:
            return _health_payload("async", backend_name)
        return _call_tool_safely("system_health", {}, root=_root(root))

    return server


async def run_mcp_from_env(env: dict[str, str] | os._Environ[str] = os.environ) -> None:
    runtime = resolve_mcp_runtime(env)
    if runtime.pg_dsn:
        import asyncpg

        pool = await asyncpg.create_pool(runtime.pg_dsn, min_size=1, max_size=runtime.pool_size)
        try:
            server = build_mcp_server(
                root=runtime.local_root,
                async_store=PgCoreStore(pool),
                backend_name=runtime.backend,
                host=runtime.host,
                port=runtime.port,
            )
            if runtime.transport == "stdio":
                await server.run_stdio_async()
            else:
                await server.run_sse_async()
        finally:
            await pool.close()
        return
    server = build_mcp_server(root=runtime.local_root, host=runtime.host, port=runtime.port)
    if runtime.transport == "stdio":
        await server.run_stdio_async()
    else:
        await server.run_sse_async()


async def run_stdio_from_env(env: dict[str, str] | os._Environ[str] = os.environ) -> None:
    runtime = dict(env)
    runtime["AEQCS_MCP_TRANSPORT"] = "stdio"
    await run_mcp_from_env(runtime)


def main() -> None:
    configure_stdio_safety()
    anyio.run(run_mcp_from_env)


if __name__ == "__main__":
    main()
