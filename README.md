# AEQCS

AEQCS is a single-node, event-driven A-share quantitative research and monitoring system.

The repository follows the v2 architecture:

- deterministic core first: auditable Python services, point-in-time data access, reproducible backtests
- cognitive layer separated by a proposal gate
- PostgreSQL as the system of record, Parquet as cold analytical storage, DuckDB for local scans
- Qlib integration where it reduces wheel reinvention, without letting Qlib own the authoritative data path
- MCP stdio server as the boundary exposed to the cognitive layer

Core blueprint: [docs/AEQCS_ARCHITECTURE_V2.md](docs/AEQCS_ARCHITECTURE_V2.md).

This scaffold implements the first development stage from the architecture document: project layout, core event schemas, look-ahead guards, storage wrappers, configuration, database bootstrap, factor/backtest interfaces, proposal gate primitives, and smoke tests.

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

To start the local stdio MCP server:

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
  factor/     factor registry, evaluation, Qlib expression hooks
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

- canonical daily bar and financial indicator records
- daily OHLCV quality checks
- PIT financial slicing helpers
- basic technical, fundamental, sentiment, and alternative factor helpers
- deterministic long-only daily backtest with next-day-open execution, basic fees, slippage, and buy-side tradability filters
- portfolio and drawdown primitives
- local CSV-backed store for development before PostgreSQL is available
- testable local implementations for key MCP tools
- local stdio MCP server for currently implemented deterministic tools
- lazy Tushare and Akshare adapters with normalized outputs
- local importers for daily bars and PIT financial indicators
- upload learning loop first pass: text/Markdown parsing, chunking, dedupe, and proposal extraction
- opt-in PostgreSQL integration test entrypoint for TimescaleDB/pgvector stores

Still pending:

- live Tushare/Akshare adapters
- live execution of the PostgreSQL integration tests against the target host
- production PostgreSQL-backed MCP service wiring and deployment verification
- production Qlib expression integration
- fuller backtest execution model: sell-side execution, volume constraints, and finer limit-up/limit-down handling
- Telegram, dashboard, report system, and full cognitive layer behavior
