# Operations Runbook

This runbook covers daily operation after AEQCS deterministic core is installed on Linux.

## Service Map

| Unit | Type | Purpose |
| --- | --- | --- |
| `mcp-server.service` | long-running service | MCP HTTP/SSE boundary for Hermes |
| `intraday.timer` / `intraday.service` | market-hours timer | deterministic intraday CEP and risk scans |
| `batch-eod.timer` / `batch-eod.service` | end-of-day timer | daily ingestion and post-close tasks |
| `batch-night.timer` / `batch-night.service` | night timer | factor, validation, archive, backup, maintenance DAG |
| `db-vacuum.timer` / `db-vacuum.service` | night timer | PostgreSQL table maintenance |
| `restore-rehearsal.timer` / `restore-rehearsal.service` | scheduled drill | isolated restore rehearsal and health check |

## Daily Checks

```bash
systemctl status mcp-server.service
systemctl list-timers 'intraday*' 'batch-*' 'db-vacuum*' 'restore-rehearsal*'
journalctl -u mcp-server.service -n 100 --no-pager
```

Then run:

```bash
cd /opt/aeqcs
sudo -u aeqcs .venv/bin/python -m scripts.verify_mcp_http_sse --endpoint http://127.0.0.1:8000/sse --connections 4
```

## Data Quality Alerts

Daily Tushare/baostock cross-check discrepancies are written as `data_quality_alerts` rows. Investigate any alert where:

- close price difference exceeds the configured threshold,
- volume difference exceeds the configured threshold,
- a source health check fails,
- the source failure policy escalates to stop/alert mode.

## Backfill Policy

Before a full historical minute backfill:

1. Run a dry-run for one or two liquid symbols.
2. Record actual baostock request count per symbol and date range.
3. Multiply by the target universe size.
4. If the estimate exceeds the configured `daily_quota` of 50000, use the cross-day checkpoint backfill plan in `aeqcs.runtime.batch`.

Never assume the first historical minute backfill can fit into one day.

## Backup And Restore

The night DAG plans database dumps, Parquet snapshots, and restore rehearsal commands. Production delivery is accepted only after a restore has been rehearsed into an isolated database and `system_health` passes against that restored database.

Manual rehearsal command:

```bash
cd /opt/aeqcs
sudo -u aeqcs .venv/bin/python -m aeqcs.runtime.batch restore-rehearsal --backup-date "$(date +%F)"
sudo -u aeqcs .venv/bin/python -m scripts.restore_rehearsal_health
```

## Resource Budget

Keep PostgreSQL connections within the configured budget:

- MCP pool: `AEQCS_MCP_POOL_SIZE`, default `8`
- batch connections: `4`
- intraday connections: `4`
- maintenance connections: `2`
- reserved connections: `2`

The default total is designed for PostgreSQL `max_connections=20`. If the database provider has a lower limit, reduce the MCP pool before starting the service.

Memory is bounded by systemd `MemoryMax=16G`. DuckDB, embedding model residency, and batch chunk sizes are configured in `aeqcs/config/settings.yaml`.

## Incident Response

MCP endpoint unhealthy:

```bash
systemctl restart mcp-server.service
journalctl -u mcp-server.service -n 200 --no-pager
```

Database permission failure:

```bash
cd /opt/aeqcs
sudo -u aeqcs .venv/bin/python -m scripts.verify_mcp_permissions
```

Backtest task stuck:

```bash
cd /opt/aeqcs
sudo -u aeqcs .venv/bin/python -m scripts.verify_mcp_backtest_recovery
```

High dead tuple ratio:

```bash
psql "$AEQCS_PG_DSN" -v ON_ERROR_STOP=1 -f /opt/aeqcs/deploy/vacuum_maintenance.sql
sudo -u aeqcs .venv/bin/python -m scripts.verify_table_bloat --dsn "$AEQCS_PG_DSN" --min-observed-hours 4
```
