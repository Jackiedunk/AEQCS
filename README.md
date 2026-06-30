# AEQCS

AEQCS is a single-node, event-driven A-share quantitative research and monitoring system.

The repository follows the v2 architecture:

- deterministic core first: auditable Python services, point-in-time data access, reproducible backtests
- cognitive layer separated by a proposal gate
- PostgreSQL as the system of record, Parquet as cold analytical storage, DuckDB for local scans
- Qlib integration where it reduces wheel reinvention, without letting Qlib own the authoritative data path
- MCP stdio server as the boundary exposed to the cognitive layer

This scaffold implements the first development stage from the architecture document: project layout, core event schemas, look-ahead guards, storage wrappers, configuration, database bootstrap, factor/backtest interfaces, proposal gate primitives, and smoke tests.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest
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
