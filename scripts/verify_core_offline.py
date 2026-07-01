"""Verify deterministic core paths without any downstream cognitive service."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta
from typing import Any

from aeqcs.core.config import load_settings, validate_connection_budget, validate_memory_resource_budget
from aeqcs.core.mcp_server import build_mcp_server
from aeqcs.runtime.batch import build_night_command_plan
from aeqcs.runtime.intraday import load_cep_rules, scan_cep_events


async def run_offline_core_selfcheck(
    *,
    local_root: str = "data/local",
    today: date | None = None,
) -> dict[str, Any]:
    run_date = today or date.today()
    settings = load_settings()
    memory_budget = validate_memory_resource_budget(settings)
    connection_budget = validate_connection_budget(settings)
    server = build_mcp_server(root=local_root)
    _content, health_payload = await server.call_tool("system_health", {})
    if not isinstance(health_payload, dict):
        health: dict[str, Any] = {
            "status": "failed",
            "error": "system_health did not return a structured payload",
        }
    else:
        health = {str(key): value for key, value in health_payload.items()}
    night_plan = build_night_command_plan(
        today=run_date,
        retention_months=3,
        archive_root="/data/aeqcs/archive/minute_bar_hot",
        backup_root="/data/backups/aeqcs",
        project_root="/opt/aeqcs",
        pg_dsn_env="AEQCS_PG_DSN",
    )
    alerts = scan_cep_events(
        [
            {
                "event_id": "offline-m1",
                "event_type": "market",
                "symbol": "000001",
                "close": 10.61,
                "pre_close": 10.0,
                "high_limit": 11.0,
                "tick_status": "TRADE",
            }
        ],
        load_cep_rules(),
    )
    _content, drawdown_risk = await server.call_tool(
        "scan_drawdown_risk",
        {
            "nav": [
                {"date": (run_date - timedelta(days=2)).isoformat(), "nav": "100"},
                {"date": (run_date - timedelta(days=1)).isoformat(), "nav": "94"},
                {"date": run_date.isoformat(), "nav": "88"},
            ],
            "warn_threshold": "0.05",
            "red_threshold": "0.10",
        },
    )
    _content, portfolio_risk = await server.call_tool(
        "scan_portfolio_risk",
        {
            "cash": "0",
            "positions": {"000001": 80, "000002": 20},
            "prices": {"000001": "10", "000002": "10"},
            "max_gross_exposure": "0.80",
            "max_single_position_weight": "0.50",
        },
    )
    budgets_ok = bool(memory_budget["within_limit"] and connection_budget["within_limit"])
    report = {
        "status": "ok"
        if health.get("status") == "ok" and alerts and drawdown_risk and portfolio_risk and budgets_ok
        else "failed",
        "system_health": health,
        "resource_budget": {
            "memory": memory_budget,
            "postgresql_connections": connection_budget,
        },
        "batch_night": {
            "dag": night_plan.dag.name,
            "tasks": [step.task_name for step in night_plan.steps],
        },
        "intraday_cep": {"alerts": alerts},
        "strategy_risk": {
            "drawdown": drawdown_risk,
            "portfolio": portfolio_risk,
        },
        "offline_boundary": {"used_external_cognitive_service": False},
    }
    return report


async def _main() -> int:
    parser = argparse.ArgumentParser(prog="verify-core-offline")
    parser.add_argument("--local-root", default="data/local")
    parser.add_argument("--today", help="Run date for deterministic batch plan, YYYY-MM-DD")
    args = parser.parse_args()
    report = await run_offline_core_selfcheck(
        local_root=args.local_root,
        today=date.fromisoformat(args.today) if args.today else None,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
