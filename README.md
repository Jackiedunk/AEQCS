# AEQCS

AEQCS is a single-node, event-driven A-share quantitative research and monitoring system.

The repository follows the v2 architecture:

- deterministic core first: auditable Python services, point-in-time data access, reproducible backtests
- cognitive layer separated by a proposal gate
- PostgreSQL as the system of record, Parquet as cold analytical storage, DuckDB for local scans
- Qlib integration where it reduces wheel reinvention, without letting Qlib own the authoritative data path
- MCP HTTP/SSE server as the boundary exposed to the cognitive layer

Core blueprint: [docs/AEQCS_ARCHITECTURE_V2.md](docs/AEQCS_ARCHITECTURE_V2.md).

This branch implements the deterministic core layer: point-in-time data access, market and financial ETL boundaries, factor evaluation, backtesting, proposal gates, deterministic graph tools, risk/portfolio utilities, event bus, MCP HTTP/SSE boundary, and deployment verification entrypoints.

## Production Guides

- Linux installation: [docs/LINUX_INSTALL.md](docs/LINUX_INSTALL.md)
- Interface setup and usage: [docs/INTERFACE_SETUP.md](docs/INTERFACE_SETUP.md)
- Operations runbook: [docs/OPERATIONS_RUNBOOK.md](docs/OPERATIONS_RUNBOOK.md)
- Production acceptance status: [docs/PRODUCTION_ACCEPTANCE.md](docs/PRODUCTION_ACCEPTANCE.md)
- PostgreSQL integration tests: [docs/POSTGRES_INTEGRATION_TESTS.md](docs/POSTGRES_INTEGRATION_TESTS.md)

## Linux Quick Install

On an Ubuntu host with Python 3.11 already installed:

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates build-essential pkg-config python3.11 python3.11-venv python3.11-dev postgresql-client
sudo git clone https://github.com/Jackiedunk/AEQCS.git /opt/aeqcs
cd /opt/aeqcs
sudo git checkout codex/deterministic-core-layer
sudo bash deploy/install_linux.sh
sudo nano /etc/aeqcs/aeqcs.env
```

Then initialize PostgreSQL/TimescaleDB:

```bash
cd /opt/aeqcs
sudo -u aeqcs .venv/bin/python deploy/init_db.py "postgresql://postgres:CHANGE_ME@127.0.0.1:5432/aeqcs"
sudo systemctl enable --now mcp-server.service
sudo -u aeqcs .venv/bin/python -m scripts.verify_mcp_http_sse --endpoint http://127.0.0.1:8000/sse --connections 8
```

The default MCP endpoint for Hermes or another trusted local client is:

```text
http://127.0.0.1:8000/sse
```

## Quick Start

Local development on Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest
```

PostgreSQL integration tests are opt-in. Use a disposable database with
TimescaleDB and pgvector available:

```powershell
$env:AEQCS_TEST_PG_DSN = "postgresql://user:password@localhost:5432/aeqcs_test"
python -m pytest tests/integration -m integration
```

See [docs/POSTGRES_INTEGRATION_TESTS.md](docs/POSTGRES_INTEGRATION_TESTS.md).

Run the deterministic smoke backtest without external data:

```powershell
python -m aeqcs.runtime.batch smoke
```

The MCP tool logic can be exercised locally with
`aeqcs.core.mcp_server.call_local_tool` and a `LocalStore` rooted at a test or
development data directory.

To start the local HTTP/SSE MCP server:

```powershell
$env:AEQCS_LOCAL_ROOT = "data/local"
aeqcs-mcp
```

To import real Tushare data into the local development store:

```powershell
python scripts/import_tushare_local.py --symbol 000001.SZ --start 2026-01-01 --end 2026-01-31 --token $env:TUSHARE_TOKEN
```

On the target Ubuntu host, use Python 3.11. The production installer uses a local virtual environment under `/opt/aeqcs/.venv`.

## Interface Summary

Runtime interfaces:

- MCP HTTP/SSE: deterministic core tools for Hermes or another local MCP client.
- Batch commands: `aeqcs.runtime.batch eod`, `night`, `smoke`, and `restore-rehearsal`.
- Intraday command: `aeqcs.runtime.intraday`.
- PostgreSQL/TimescaleDB: authoritative store with restricted MCP role.

Key environment variables:

- `AEQCS_PG_DSN`: full core database role for batch, ingestion, maintenance, and verification.
- `AEQCS_CORE_PG_DSN`: restricted MCP role used by `mcp-server.service`.
- `AEQCS_MCP_TRANSPORT=sse`
- `AEQCS_MCP_HOST=127.0.0.1`
- `AEQCS_MCP_PORT=8000`
- `AEQCS_MCP_POOL_SIZE=8`
- `TUSHARE_TOKEN`: required for PIT financial data.
- `AEQCS_RESTORE_PG_DSN`: isolated restore rehearsal database.

See [docs/INTERFACE_SETUP.md](docs/INTERFACE_SETUP.md) for the MCP tool list and caller contract.

## Layout

```text
aeqcs/
  core/       deterministic event, clock, versioning, MCP boundary
  store/      PostgreSQL, Parquet, DuckDB access helpers
  data/       source adapters, ETL, validation, Qlib adapter
  factor/     factor registry, evaluation, pipeline, genetic miner, risk model
  strategy/   tradability, event-driven backtest, performance analysis
  gate/       proposals, validation, promotion boundary
  knowledge/  semantic network and universe builder
  runtime/    intraday and batch entrypoints
deploy/       PostgreSQL bootstrap, systemd units, OS tuning
tests/        unit and look-ahead tests
```

## Data Source Policy

- Tushare is the authoritative source for PIT financial/fundamental data and the primary daily market path.
- baostock is used only for historical minute data and daily cross-checks.
- baostock data is pulled as raw unadjusted prices (`adjustflag=3`); AEQCS owns adjustment-factor logic.
- baostock is serialized through a process-global lock and guarded by a daily quota.

## Non-Negotiables

- Any data read that can influence research or trading must carry `as_of_date`.
- Cognitive output may only enter the core as proposals.
- Backtests execute against data known at the decision time.
- Intraday monitoring is alert-only; no automatic intraday execution.

## Verification

Core local verification:

```bash
python -m pytest
python -m aeqcs.runtime.batch smoke
python -m scripts.verify_core_offline
```

Live MCP/SSE verification:

```bash
python -m scripts.verify_mcp_http_sse --endpoint http://127.0.0.1:8000/sse --connections 8
```

PostgreSQL/TimescaleDB verification:

```bash
export AEQCS_TEST_PG_DSN="postgresql://user:password@host:5432/aeqcs_test?sslmode=require"
python -m pytest tests/integration -m integration
python -m scripts.verify_mcp_permissions
python -m scripts.verify_mcp_backtest_recovery
```

## Current Development Status

Implemented:

- deterministic core MCP tools over HTTP/SSE
- LocalStore and PostgreSQL/TimescaleDB store boundaries
- PIT market, financial, index-constituent, and stock-universe access
- Tushare financial path and baostock market-data path
- baostock minute source, daily cross-check, daily quota, and no-concurrency lock
- vintage assignment, dual adjusted-price output, and corporate-action state helpers
- factor registry, factor pipeline, genetic miner, risk model helpers, and rolling validation gate
- deterministic backtest task persistence and recovery
- strategy risk and portfolio risk scans
- event bus with lightweight PG NOTIFY payloads
- systemd units, night DAG plans, restore rehearsal plans, and production verification scripts

Acceptance status:

- local suite: `479 passed, 3 skipped`
- full suite with real TimescaleDB integration DSN: `482 passed`
- production deployment acceptance is in progress; see [docs/PRODUCTION_ACCEPTANCE.md](docs/PRODUCTION_ACCEPTANCE.md)
