"""Verify MCP backtest task recovery against a PostgreSQL store."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime
from typing import Any

import asyncpg

from aeqcs.core.mcp_server import build_mcp_server, normalize_asyncpg_dsn
from aeqcs.store.pg_core import PgCoreStore


RECOVERY_TASK_IDS = (
    "mcp-recovery-rehearsal-task",
    "mcp-recovery-rehearsal-result",
)
RECOVERY_ERROR_FRAGMENT = "MCP process restart"


def build_orphaned_backtest_task(task_id: str) -> dict[str, Any]:
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


def evaluate_recovery_payload(payload: dict[str, Any], expected_task_id: str) -> dict[str, Any]:
    recovered_status = payload.get("status")
    error = payload.get("error")
    ok = (
        payload.get("task_id") == expected_task_id
        and recovered_status == "failed"
        and isinstance(error, str)
        and RECOVERY_ERROR_FRAGMENT in error
    )
    return {
        "task_id": expected_task_id,
        "status": "ok" if ok else "failed",
        "recovered_status": recovered_status,
        "error": error,
    }


def require_structured_payload(payload: Any, tool_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError(f"{tool_name} did not return a structured payload")
    return payload


async def run_recovery_rehearsal(dsn: str) -> dict[str, Any]:
    pool = await asyncpg.create_pool(normalize_asyncpg_dsn(dsn), min_size=1, max_size=1)
    try:
        store = PgCoreStore(pool)
        for task_id in RECOVERY_TASK_IDS:
            await store.save_backtest_task(build_orphaned_backtest_task(task_id))

        server = build_mcp_server(async_store=store, backend_name="postgresql-recovery-rehearsal")
        _content, task_payload = await server.call_tool(
            "get_backtest_task",
            {"task_id": RECOVERY_TASK_IDS[0]},
        )
        _content, result_payload = await server.call_tool(
            "get_backtest_result",
            {"backtest_result_id": RECOVERY_TASK_IDS[1]},
        )
        checks = [
            {
                "tool": "get_backtest_task",
                **evaluate_recovery_payload(
                    require_structured_payload(task_payload, "get_backtest_task"),
                    RECOVERY_TASK_IDS[0],
                ),
            },
            {
                "tool": "get_backtest_result",
                **evaluate_recovery_payload(
                    require_structured_payload(result_payload, "get_backtest_result"),
                    RECOVERY_TASK_IDS[1],
                ),
            },
        ]
        return {
            "status": "ok" if all(check["status"] == "ok" for check in checks) else "failed",
            "checks": checks,
        }
    finally:
        await pool.close()


async def _main() -> int:
    dsn = os.environ.get("AEQCS_RECOVERY_PG_DSN") or os.environ.get("AEQCS_CORE_PG_DSN")
    if not dsn:
        print("AEQCS_RECOVERY_PG_DSN or AEQCS_CORE_PG_DSN is required", file=sys.stderr)
        return 2
    report = await run_recovery_rehearsal(dsn)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, default=str))
    return 0 if report["status"] == "ok" else 1


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
