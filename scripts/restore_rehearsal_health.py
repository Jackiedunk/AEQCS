"""Run system_health against an isolated restore database."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import asyncpg

from aeqcs.core.mcp_server import build_mcp_server, normalize_asyncpg_dsn
from aeqcs.store.pg_core import PgCoreStore


RESTORE_REHEARSAL_BACKEND = "postgresql-restore-rehearsal"


def build_restore_rehearsal_report(system_health: dict[str, Any]) -> dict[str, Any]:
    payload = {str(key): value for key, value in system_health.items()}
    resource_budget = payload.get("resource_budget")
    resource_ok = isinstance(resource_budget, dict) and resource_budget.get("within_limit") is True
    backend = payload.get("backend")
    health_status = payload.get("status")
    rehearsal_ok = health_status == "ok" and backend == RESTORE_REHEARSAL_BACKEND and resource_ok

    return {
        "status": "ok" if rehearsal_ok else "failed",
        "restore_rehearsal": {
            "isolated_database": backend == RESTORE_REHEARSAL_BACKEND,
            "backend": backend,
            "system_health_status": health_status,
        },
        "resource_budget": resource_budget,
        "system_health": payload,
    }


async def _main() -> int:
    dsn = os.environ.get("AEQCS_RESTORE_PG_DSN")
    if not dsn:
        print("AEQCS_RESTORE_PG_DSN is required", file=sys.stderr)
        return 2

    pool = await asyncpg.create_pool(normalize_asyncpg_dsn(dsn), min_size=1, max_size=1)
    try:
        server = build_mcp_server(
            async_store=PgCoreStore(pool),
            backend_name="postgresql-restore-rehearsal",
        )
        _content, raw_payload = await server.call_tool("system_health", {})
        if not isinstance(raw_payload, dict):
            print("system_health did not return a structured payload", file=sys.stderr)
            return 1
        report = build_restore_rehearsal_report(raw_payload)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["status"] == "ok" else 1
    finally:
        await pool.close()


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
