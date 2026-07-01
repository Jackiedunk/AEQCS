# AEQCS Production Acceptance

Date: 2026-07-01
Branch: `codex/deterministic-core-layer`
Commit before acceptance fix: `119e38d`

This document tracks deployment acceptance for the deterministic core layer. It separates checks that have actually run from checks that require the target Linux/systemd host.

## Accepted In Current Environment

| Check | Result | Evidence |
| --- | --- | --- |
| Local full test suite | Passed | `479 passed, 3 skipped` after the MCP recovery regression test was added |
| Full suite with real TimescaleDB integration DSN | Passed | `482 passed` |
| Real TimescaleDB integration tests | Passed | `tests/integration -m integration`: `3 passed` |
| Offline deterministic core self-check | Passed | `scripts.verify_core_offline`: `status=ok` |
| Local MCP concurrency self-check | Passed | `scripts.verify_mcp_concurrency --concurrency 16`: `status=ok`, 80 calls, 0 failures |
| Night batch DAG command plan | Passed | `aeqcs.runtime.batch night` emits backup, archive, vacuum, HNSW reindex, and inbox parse order |
| Restore rehearsal command plan | Passed | `aeqcs.runtime.batch restore-rehearsal --backup-date 2026-07-01` emits restore, parquet verification, and health-check steps |
| MCP restricted-role grants on real TimescaleDB | Passed | `scripts.verify_mcp_permissions`: `status=ok` |
| MCP orphaned backtest recovery on real TimescaleDB | Passed after fix | `scripts.verify_mcp_backtest_recovery`: `status=ok` |
| Secret scan before publish | Passed | No database password or API token found in tracked project files |

## Fixed During Acceptance

The real PostgreSQL recovery rehearsal exposed a type boundary bug in MCP orphaned backtest recovery.

Root cause: the MCP tool converted a PostgreSQL task row to JSON-friendly strings before writing the recovered task back to `backtest_tasks`; asyncpg expects Python `date` values for date columns.

Fix: recover with the raw store payload first, then apply JSON normalization only to the outbound MCP response.

Regression: `test_mcp_orphaned_backtest_recovery_preserves_pg_date_types`.

## Still Requires Target Host

| Check | Required environment | Status |
| --- | --- | --- |
| systemd service start for `mcp-server.service` | Linux host with systemd | Pending |
| HTTP/SSE probe against live `127.0.0.1:8000/sse` | Running MCP service on target host | Pending |
| cgroup `MemoryMax=16G` enforcement | Linux host with systemd/cgroup | Pending |
| Four-hour intraday load | Target host with scheduled intraday process | Pending |
| Table-bloat recheck after four-hour load | Target PostgreSQL/TimescaleDB after observation window | Pending |
| Real restore rehearsal | Isolated restore database plus latest pg dump and Parquet snapshot | Pending |
| baostock minute full-history dry-run | Network access to baostock from the runtime host | Pending |
| baostock full-market backfill quota decision | Result of dry-run request-count estimate | Pending |

## Current Table-Bloat Probe

The current probe was not accepted as a pass because no four-hour observation window has run yet.

Observed result:

- `observed_hours`: 0
- `status`: failed as expected for insufficient observation
- `proposals` had dead tuples in the test database

This should be rerun after the target intraday process has operated for at least four hours.

## Target-Host Commands

Run these on the deployment host after installing the branch and setting environment variables through secure service files or shell session variables:

```bash
python -m scripts.verify_core_offline
python -m scripts.verify_mcp_http_sse --endpoint http://127.0.0.1:8000/sse --connections 8
python -m scripts.verify_mcp_permissions
python -m scripts.verify_mcp_backtest_recovery
python -m scripts.verify_risk_alert_delivery
python -m scripts.verify_table_bloat --observed-hours 4
python -m aeqcs.runtime.batch restore-rehearsal --backup-date YYYY-MM-DD
```

Do not put database passwords or data-source tokens in this file. Use environment variables or systemd environment files with restricted permissions.
