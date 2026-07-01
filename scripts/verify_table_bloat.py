"""Verify PostgreSQL hot-table dead tuple ratios after an intraday run."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any


HOT_WRITE_TABLES = (
    "signal_log",
    "proposals",
    "cooccurrence_cache",
    "minute_bar_hot",
)


def evaluate_table_bloat(
    rows: list[dict[str, Any]],
    *,
    observed_hours: float,
    min_observed_hours: float = 4,
    max_dead_tuple_ratio: float = 0.10,
) -> dict[str, Any]:
    table_rows = {str(row["relname"]): row for row in rows}
    failures: list[dict[str, Any]] = []
    if observed_hours < min_observed_hours:
        failures.append(
            {
                "reason": "insufficient_observation_window",
                "observed_hours": observed_hours,
                "min_observed_hours": min_observed_hours,
            }
        )
    tables: dict[str, dict[str, Any]] = {}
    for table in HOT_WRITE_TABLES:
        row = table_rows.get(table)
        if row is None:
            continue
        live = int(row.get("n_live_tup", 0) or 0)
        dead = int(row.get("n_dead_tup", 0) or 0)
        total = live + dead
        ratio = 0.0 if total == 0 else round(dead / total, 6)
        tables[table] = {
            "n_live_tup": live,
            "n_dead_tup": dead,
            "dead_tuple_ratio": ratio,
        }
        if ratio > max_dead_tuple_ratio:
            failures.append(
                {
                    "table": table,
                    "reason": "dead_tuple_ratio_exceeded",
                    "dead_tuple_ratio": ratio,
                    "max_dead_tuple_ratio": max_dead_tuple_ratio,
                }
            )
    return {
        "status": "ok" if not failures else "failed",
        "observed_hours": observed_hours,
        "min_observed_hours": min_observed_hours,
        "max_dead_tuple_ratio": max_dead_tuple_ratio,
        "tables": tables,
        "failures": failures,
    }


async def fetch_table_bloat_stats(dsn: str) -> list[dict[str, Any]]:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT relname, n_live_tup, n_dead_tup, last_vacuum, last_autovacuum
            FROM pg_stat_user_tables
            WHERE relname = ANY($1::text[])
            ORDER BY relname
            """,
            list(HOT_WRITE_TABLES),
        )
        return [dict(row) for row in rows]
    finally:
        await conn.close()


async def run_table_bloat_check(
    *,
    dsn: str,
    observed_hours: float,
    min_observed_hours: float = 4,
    max_dead_tuple_ratio: float = 0.10,
) -> dict[str, Any]:
    rows = await fetch_table_bloat_stats(dsn)
    return evaluate_table_bloat(
        rows,
        observed_hours=observed_hours,
        min_observed_hours=min_observed_hours,
        max_dead_tuple_ratio=max_dead_tuple_ratio,
    )


async def _main() -> int:
    parser = argparse.ArgumentParser(prog="verify-table-bloat")
    parser.add_argument("--dsn", default=os.environ.get("AEQCS_PG_DSN"))
    parser.add_argument("--observed-hours", type=float, required=True)
    parser.add_argument("--min-observed-hours", type=float, default=4)
    parser.add_argument("--max-dead-tuple-ratio", type=float, default=0.10)
    args = parser.parse_args()
    if not args.dsn:
        raise SystemExit("PostgreSQL DSN is required via --dsn or AEQCS_PG_DSN")
    report = await run_table_bloat_check(
        dsn=args.dsn,
        observed_hours=args.observed_hours,
        min_observed_hours=args.min_observed_hours,
        max_dead_tuple_ratio=args.max_dead_tuple_ratio,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, default=str))
    return 0 if report["status"] == "ok" else 1


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
