"""MCP stdio server boundary for the deterministic core."""

from __future__ import annotations

from datetime import date
from typing import Any

from aeqcs.core.json import to_jsonable
from aeqcs.core.service import CoreService
from aeqcs.store.local import LocalStore


def tool_manifest() -> list[dict[str, Any]]:
    return [
        {"name": "get_market_data", "requires_as_of": True},
        {"name": "get_financials", "requires_as_of": True},
        {"name": "search_semantic_nodes", "requires_as_of": False},
        {"name": "get_concept_stocks", "requires_as_of": False},
        {"name": "submit_proposal", "requires_as_of": False},
        {"name": "get_proposal_status", "requires_as_of": False},
        {"name": "run_backtest", "requires_as_of": True},
        {"name": "get_backtest_result", "requires_as_of": False},
        {"name": "compute_factors", "requires_as_of": True},
        {"name": "load_inbox", "requires_as_of": False},
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
    if name == "compute_factors":
        return to_jsonable(
            service.compute_factors(
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
    if name == "system_health":
        return {"status": "ok", "store": root, "tools": [tool["name"] for tool in tool_manifest()]}
    raise ValueError(f"unsupported local tool: {name}")


def main() -> None:
    raise SystemExit(
        "MCP transport wiring is intentionally left for the deployment host. "
        "Use tool_manifest() as the contract while storage credentials are configured."
    )
