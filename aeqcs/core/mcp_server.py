"""MCP stdio server boundary for the deterministic core."""

from __future__ import annotations

from typing import Any


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


def main() -> None:
    raise SystemExit(
        "MCP transport wiring is intentionally left for the deployment host. "
        "Use tool_manifest() as the contract while storage credentials are configured."
    )
