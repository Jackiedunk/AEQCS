"""MCP stdio server boundary for the deterministic core."""

from __future__ import annotations

import os
import sys
import logging
from contextlib import redirect_stdout
from datetime import date
from typing import Any

from mcp.server.fastmcp import FastMCP

from aeqcs.core.json import to_jsonable
from aeqcs.core.service import CoreService
from aeqcs.store.local import LocalStore


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
        {"name": "submit_proposal", "requires_as_of": False},
        {"name": "get_proposal_status", "requires_as_of": False},
        {"name": "review_proposal", "requires_as_of": False},
        {"name": "run_backtest", "requires_as_of": True},
        {"name": "get_backtest_result", "requires_as_of": False},
        {"name": "compute_factors", "requires_as_of": True},
        {"name": "get_factor_values", "requires_as_of": True},
        {"name": "load_inbox", "requires_as_of": False},
        {"name": "get_uploaded_doc", "requires_as_of": False},
        {"name": "system_health", "requires_as_of": False},
    ]


def local_service(root: str = "data/local") -> CoreService:
    return CoreService(LocalStore(root))


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def call_local_tool(name: str, arguments: dict[str, Any], root: str = "data/local") -> Any:
    """Call a tool implementation without MCP transport.

    This keeps the deterministic contract testable before stdio wiring and
    PostgreSQL credentials are available.
    """

    service = local_service(root)
    if name == "get_market_data":
        return to_jsonable(service.get_market_data(arguments["symbol"], parse_date(arguments["as_of_date"])))
    if name == "get_financials":
        return to_jsonable(
            service.get_financials(
                arguments["symbol"],
                arguments["period"],
                parse_date(arguments["as_of_date"]),
            )
        )
    if name == "load_inbox":
        return to_jsonable(
            service.load_inbox(
                arguments["filename"],
                arguments["content_base64"],
                arguments.get("doc_type", "note"),
            )
        )
    if name == "get_uploaded_doc":
        return to_jsonable(service.get_uploaded_doc(arguments["sha256"]))
    if name == "compute_factors":
        return to_jsonable(
            service.compute_factors(
                list(arguments["factor_ids"]),
                parse_date(arguments["start_date"]),
                parse_date(arguments["end_date"]),
                parse_date(arguments["as_of_date"]),
            )
        )
    if name == "get_factor_values":
        return to_jsonable(
            service.get_factor_values(
                list(arguments["factor_ids"]),
                parse_date(arguments["start_date"]),
                parse_date(arguments["end_date"]),
                parse_date(arguments["as_of_date"]),
            )
        )
    if name == "run_backtest":
        return to_jsonable(
            service.run_backtest(
                arguments["strategy_name"],
                parse_date(arguments["start_date"]),
                parse_date(arguments["end_date"]),
                dict(arguments.get("parameters", {})),
                parse_date(arguments["as_of_date"]),
            )
        )
    if name == "get_backtest_result":
        return to_jsonable(service.get_backtest_result(arguments["backtest_result_id"]))
    if name == "submit_proposal":
        return service.submit_proposal(
            arguments["kind"],
            dict(arguments["payload"]),
            arguments["source"],
            float(arguments["confidence"]),
            arguments.get("snapshot_id"),
        )
    if name == "get_proposal_status":
        return to_jsonable(service.get_proposal_status(int(arguments["proposal_id"])))
    if name == "review_proposal":
        return to_jsonable(
            service.review_proposal(
                int(arguments["proposal_id"]),
                arguments["status"],
                arguments["reviewed_by"],
                arguments.get("reason", ""),
                arguments.get("backtest_result"),
            )
        )
    if name == "system_health":
        return {"status": "ok", "store": root, "tools": [tool["name"] for tool in tool_manifest()]}
    raise ValueError(f"unsupported local tool: {name}")


def _root(default: str) -> str:
    return os.environ.get("AEQCS_LOCAL_ROOT", default)


def _call_tool_safely(name: str, arguments: dict[str, Any], root: str) -> Any:
    with redirect_stdout(sys.stderr):
        return call_local_tool(name, arguments, root=root)


def build_mcp_server(root: str = "data/local") -> FastMCP:
    server = FastMCP(
        "aeqcs-core",
        instructions=(
            "AEQCS deterministic core tools. All time-sensitive market and "
            "factor queries require an explicit as_of_date."
        ),
    )

    @server.tool(description="Get latest market row for a symbol at an explicit as-of date.")
    def get_market_data(symbol: str, as_of_date: str) -> dict[str, Any]:
        return _call_tool_safely(
            "get_market_data",
            {"symbol": symbol, "as_of_date": as_of_date},
            root=_root(root),
        )

    @server.tool(description="Get point-in-time financial indicators for a symbol and period.")
    def get_financials(symbol: str, period: str, as_of_date: str) -> dict[str, Any]:
        return _call_tool_safely(
            "get_financials",
            {"symbol": symbol, "period": period, "as_of_date": as_of_date},
            root=_root(root),
        )

    @server.tool(description="Submit a proposed factor, correction, or strategy change to the gate.")
    def submit_proposal(
        kind: str,
        payload: dict[str, Any],
        source: str,
        confidence: float,
        snapshot_id: int | None = None,
    ) -> int:
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
    def get_proposal_status(proposal_id: int) -> dict[str, Any]:
        return _call_tool_safely("get_proposal_status", {"proposal_id": proposal_id}, root=_root(root))

    @server.tool(description="Review a proposal and advance it through the gate state machine.")
    def review_proposal(
        proposal_id: int,
        status: str,
        reviewed_by: str,
        reason: str = "",
        backtest_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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

    @server.tool(description="Run a deterministic daily backtest with explicit as-of protection.")
    def run_backtest(
        strategy_name: str,
        start_date: str,
        end_date: str,
        parameters: dict[str, Any],
        as_of_date: str,
    ) -> dict[str, Any]:
        return _call_tool_safely(
            "run_backtest",
            {
                "strategy_name": strategy_name,
                "start_date": start_date,
                "end_date": end_date,
                "parameters": parameters,
                "as_of_date": as_of_date,
            },
            root=_root(root),
        )

    @server.tool(description="Get a persisted backtest report by id.")
    def get_backtest_result(backtest_result_id: str) -> dict[str, Any]:
        return _call_tool_safely(
            "get_backtest_result",
            {"backtest_result_id": backtest_result_id},
            root=_root(root),
        )

    @server.tool(description="Compute supported deterministic factors and persist the values.")
    def compute_factors(
        factor_ids: list[str],
        start_date: str,
        end_date: str,
        as_of_date: str,
    ) -> list[dict[str, Any]]:
        return _call_tool_safely(
            "compute_factors",
            {
                "factor_ids": factor_ids,
                "start_date": start_date,
                "end_date": end_date,
                "as_of_date": as_of_date,
            },
            root=_root(root),
        )

    @server.tool(description="Query persisted factor values with explicit as-of protection.")
    def get_factor_values(
        factor_ids: list[str],
        start_date: str,
        end_date: str,
        as_of_date: str,
    ) -> list[dict[str, Any]]:
        return _call_tool_safely(
            "get_factor_values",
            {
                "factor_ids": factor_ids,
                "start_date": start_date,
                "end_date": end_date,
                "as_of_date": as_of_date,
            },
            root=_root(root),
        )

    @server.tool(description="Upload a text or Markdown document into the local inbox.")
    def load_inbox(filename: str, content_base64: str, doc_type: str = "note") -> dict[str, Any]:
        return _call_tool_safely(
            "load_inbox",
            {"filename": filename, "content_base64": content_base64, "doc_type": doc_type},
            root=_root(root),
        )

    @server.tool(description="Get an uploaded document and its chunks by sha256.")
    def get_uploaded_doc(sha256: str) -> dict[str, Any]:
        return _call_tool_safely("get_uploaded_doc", {"sha256": sha256}, root=_root(root))

    @server.tool(description="Return local AEQCS core health and registered tool names.")
    def system_health() -> dict[str, Any]:
        return _call_tool_safely("system_health", {}, root=_root(root))

    return server


def main() -> None:
    configure_stdio_safety()
    build_mcp_server().run(transport="stdio")
