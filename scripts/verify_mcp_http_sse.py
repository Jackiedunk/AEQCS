"""Run an HTTP/SSE MCP multi-connection probe against a deployed core service."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from mcp import ClientSession
from mcp.client.sse import sse_client

DEFAULT_ENDPOINT = "http://127.0.0.1:8000/sse"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _tool_specs() -> list[dict[str, Any]]:
    return [
        {"name": "system_health", "arguments": {}},
        {
            "name": "scan_intraday_events",
            "arguments": {
                "events": [
                    {
                        "event_id": "http-sse-m1",
                        "event_type": "market",
                        "symbol": "000001",
                        "close": 10.61,
                        "pre_close": 10.0,
                        "high_limit": 11.0,
                        "tick_status": "TRADE",
                    }
                ]
            },
        },
        {
            "name": "scan_drawdown_risk",
            "arguments": {
                "nav": [
                    {"date": "2026-01-01", "nav": "100"},
                    {"date": "2026-01-02", "nav": "94"},
                    {"date": "2026-01-03", "nav": "88"},
                ],
                "warn_threshold": "0.05",
                "red_threshold": "0.10",
            },
        },
        {
            "name": "scan_portfolio_risk",
            "arguments": {
                "cash": "0",
                "positions": {"000001": 80, "000002": 20},
                "prices": {"000001": "10", "000002": "10"},
                "max_gross_exposure": "0.80",
                "max_single_position_weight": "0.50",
            },
        },
        {
            "name": "get_market_data",
            "arguments": {
                "symbol": "000001",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "as_of_date": "2026-01-02",
                "limit": 10,
                "offset": 0,
            },
        },
    ]


def build_http_sse_probe_plan(
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    connections: int = 16,
) -> dict[str, Any]:
    if not endpoint:
        raise ValueError("endpoint is required")
    parsed = urlparse(endpoint)
    if parsed.hostname not in LOOPBACK_HOSTS:
        raise ValueError("HTTP/SSE probe endpoint must use a loopback host")
    if connections < 1:
        raise ValueError("connections must be greater than 0")
    return {
        "transport": "sse",
        "endpoint": endpoint,
        "connections": connections,
        "tools": _tool_specs(),
    }


def summarize_probe_results(plan: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    tools = [str(tool["name"]) for tool in plan["tools"]]
    connections = int(plan["connections"])
    calls_per_connection = len(tools)
    failures = [result for result in results if not result.get("ok")]
    tool_counts = {
        name: sum(1 for result in results if result.get("tool") == name and result.get("ok"))
        for name in tools
    }
    expected_count = connections
    missing_calls = [
        {"tool": name, "expected": expected_count, "observed": count}
        for name, count in tool_counts.items()
        if count != expected_count
    ]
    return {
        "status": "ok" if not failures and not missing_calls else "failed",
        "transport": plan["transport"],
        "endpoint": plan["endpoint"],
        "connections": connections,
        "calls_per_connection": calls_per_connection,
        "total_calls": len(results),
        "expected_total_calls": connections * calls_per_connection,
        "tool_counts": tool_counts,
        "missing_calls": missing_calls,
        "failures": failures,
    }


async def _run_connection(
    *,
    connection: int,
    endpoint: str,
    tools: list[dict[str, Any]],
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    connection_results: list[dict[str, Any]] = []
    try:
        async with sse_client(
            endpoint,
            timeout=timeout_seconds,
            sse_read_timeout=timeout_seconds,
        ) as (read, write):
            async with ClientSession(
                read,
                write,
                read_timeout_seconds=timedelta(seconds=timeout_seconds),
            ) as session:
                await session.initialize()
                for tool in tools:
                    name = str(tool["name"])
                    try:
                        result = await session.call_tool(
                            name,
                            tool["arguments"],
                            read_timeout_seconds=timedelta(seconds=timeout_seconds),
                        )
                        connection_results.append(
                            {
                                "connection": connection,
                                "tool": name,
                                "ok": not result.isError,
                                "is_error": result.isError,
                            }
                        )
                    except Exception as exc:
                        connection_results.append(
                            {
                                "connection": connection,
                                "tool": name,
                                "ok": False,
                                "error": str(exc),
                            }
                        )
    except Exception as exc:
        for tool in tools:
            connection_results.append(
                {
                    "connection": connection,
                    "tool": str(tool["name"]),
                    "ok": False,
                    "error": str(exc),
                }
            )
    return connection_results


async def run_http_sse_probe(
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    connections: int = 16,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    plan = build_http_sse_probe_plan(endpoint=endpoint, connections=connections)
    batches = await asyncio.gather(
        *(
            _run_connection(
                connection=index,
                endpoint=endpoint,
                tools=plan["tools"],
                timeout_seconds=timeout_seconds,
            )
            for index in range(connections)
        )
    )
    results = [result for batch in batches for result in batch]
    return summarize_probe_results(plan, results)


async def _main() -> int:
    parser = argparse.ArgumentParser(prog="verify-mcp-http-sse")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--connections", type=int, default=16)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    args = parser.parse_args()
    report = await run_http_sse_probe(
        endpoint=args.endpoint,
        connections=args.connections,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
