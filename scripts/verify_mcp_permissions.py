"""Verify restricted PostgreSQL grants for the AEQCS MCP role."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import asyncpg

from aeqcs.core.mcp_server import normalize_asyncpg_dsn


MCP_ROLE = "aeqcs_mcp"

REQUIRED_TABLE_PRIVILEGES: dict[str, set[str]] = {
    "stock_daily_origin": {"SELECT"},
    "financial_indicators": {"SELECT"},
    "index_constituents": {"SELECT"},
    "factor_values": {"SELECT", "INSERT", "UPDATE"},
    "backtest_results": {"SELECT", "INSERT", "UPDATE"},
    "backtest_tasks": {"SELECT", "INSERT", "UPDATE"},
    "uploaded_docs": {"SELECT", "INSERT", "UPDATE"},
    "doc_chunks": {"SELECT", "INSERT", "UPDATE"},
    "proposals": {"SELECT", "INSERT", "UPDATE"},
    "semantic_nodes": {"SELECT", "INSERT", "UPDATE"},
    "semantic_edges": {"SELECT", "INSERT", "UPDATE"},
    "event_log": {"SELECT", "INSERT"},
    "event_consumptions": {"SELECT", "INSERT"},
}

FORBIDDEN_TABLE_PRIVILEGES: dict[str, set[str]] = {
    "stock_daily_origin": {"INSERT", "UPDATE", "DELETE"},
    "financial_indicators": {"INSERT", "UPDATE", "DELETE"},
    "index_constituents": {"INSERT", "UPDATE", "DELETE"},
    "event_log": {"UPDATE", "DELETE"},
    "event_consumptions": {"UPDATE", "DELETE"},
}


def _grant_map(rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    grants: dict[str, set[str]] = {}
    for row in rows:
        table_name = str(row["table_name"])
        privilege = str(row["privilege_type"]).upper()
        grants.setdefault(table_name, set()).add(privilege)
    return grants


def audit_table_privileges(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grants = _grant_map(rows)
    missing_required = [
        {"table": table, "privilege": privilege}
        for table, privileges in sorted(REQUIRED_TABLE_PRIVILEGES.items())
        for privilege in sorted(privileges - grants.get(table, set()))
    ]
    forbidden_present = [
        {"table": table, "privilege": privilege}
        for table, privileges in sorted(FORBIDDEN_TABLE_PRIVILEGES.items())
        for privilege in sorted(privileges & grants.get(table, set()))
    ]
    return {
        "role": MCP_ROLE,
        "status": "ok" if not missing_required and not forbidden_present else "failed",
        "missing_required": missing_required,
        "forbidden_present": forbidden_present,
    }


async def _fetch_table_grants(dsn: str) -> list[dict[str, Any]]:
    conn = await asyncpg.connect(normalize_asyncpg_dsn(dsn))
    try:
        rows = await conn.fetch(
            """
            SELECT table_name, privilege_type
            FROM information_schema.role_table_grants
            WHERE grantee=$1
              AND table_schema='public'
            ORDER BY table_name, privilege_type
            """,
            MCP_ROLE,
        )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def _main() -> int:
    dsn = os.environ.get("AEQCS_PG_DSN") or os.environ.get("AEQCS_CORE_PG_DSN")
    if not dsn:
        print("AEQCS_PG_DSN or AEQCS_CORE_PG_DSN is required", file=sys.stderr)
        return 2
    report = audit_table_privileges(await _fetch_table_grants(dsn))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
