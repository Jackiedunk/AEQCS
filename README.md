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

## Quick Start

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

On the target Ubuntu host, use Python 3.11 and `uv`.

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

## Non-Negotiables

- Any data read that can influence research or trading must carry `as_of_date`.
- Cognitive output may only enter the core as proposals.
- Backtests execute against data known at the decision time.
- Intraday monitoring is alert-only; no automatic intraday execution.

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
