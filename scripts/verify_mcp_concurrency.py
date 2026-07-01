"""Run a deterministic MCP concurrent tool-call self-check."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from aeqcs.core.mcp_server import build_mcp_server


async def run_mcp_concurrency_selfcheck(
    *,
    local_root: str = "data/local",
    concurrency: int = 16,
) -> dict[str, Any]:
    if concurrency < 1:
        raise ValueError("concurrency must be greater than 0")
    server = build_mcp_server(root=local_root)
    tool_specs: list[tuple[str, dict[str, Any]]] = [
        ("system_health", {}),
        (
            "scan_intraday_events",
            {
                "events": [
                    {
                        "event_id": "concurrency-m1",
                        "event_type": "market",
                        "symbol": "000001",
                        "close": 10.61,
                        "pre_close": 10.0,
                        "high_limit": 11.0,
                        "tick_status": "TRADE",
                    }
                ]
            },
        ),
        (
            "scan_drawdown_risk",
            {
                "nav": [
                    {"date": "2026-01-01", "nav": "100"},
                    {"date": "2026-01-02", "nav": "94"},
                    {"date": "2026-01-03", "nav": "88"},
                ],
                "warn_threshold": "0.05",
                "red_threshold": "0.10",
            },
        ),
        (
            "scan_portfolio_risk",
            {
                "cash": "0",
                "positions": {"000001": 80, "000002": 20},
                "prices": {"000001": "10", "000002": "10"},
                "max_gross_exposure": "0.80",
                "max_single_position_weight": "0.50",
            },
        ),
        (
            "get_market_data",
            {
                "symbol": "000001",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "as_of_date": "2026-01-02",
                "limit": 10,
                "offset": 0,
            },
        ),
    ]

    async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            _content, payload = await server.call_tool(name, arguments)
            return {"tool": name, "ok": True, "payload": payload}
        except Exception as exc:
            return {"tool": name, "ok": False, "error": str(exc)}

    tasks = [
        call_tool(name, arguments)
        for _index in range(concurrency)
        for name, arguments in tool_specs
    ]
    results = await asyncio.gather(*tasks)
    failures = [result for result in results if not result["ok"]]
    tool_counts = {
        name: sum(1 for result in results if result["tool"] == name and result["ok"])
        for name, _arguments in tool_specs
    }
    sample_results: dict[str, Any] = {}
    for result in results:
        if result["ok"] and result["tool"] not in sample_results:
            sample_results[result["tool"]] = result["payload"]
    observed_tools = []
    health = sample_results.get("system_health")
    if isinstance(health, dict):
        observed_tools = list(health.get("tools", []))
    return {
        "status": "ok" if not failures and all(count == concurrency for count in tool_counts.values()) else "failed",
        "concurrency": concurrency,
        "total_calls": len(results),
        "tool_counts": tool_counts,
        "failures": failures,
        "sample_results": sample_results,
        "observed_tools": observed_tools,
    }


async def _main() -> int:
    parser = argparse.ArgumentParser(prog="verify-mcp-concurrency")
    parser.add_argument("--local-root", default="data/local")
    parser.add_argument("--concurrency", type=int, default=16)
    args = parser.parse_args()
    report = await run_mcp_concurrency_selfcheck(
        local_root=args.local_root,
        concurrency=args.concurrency,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
