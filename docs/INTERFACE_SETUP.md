# Interface Setup And Usage

AEQCS deterministic core exposes one primary runtime interface: MCP over HTTP/SSE. Data ingestion and batch jobs are command interfaces. The cognitive layer, including Hermes, is a client of this core; the core never calls Hermes synchronously.

## MCP HTTP/SSE

Default endpoint:

```text
http://127.0.0.1:8000/sse
```

Environment:

```bash
AEQCS_MCP_TRANSPORT=sse
AEQCS_MCP_HOST=127.0.0.1
AEQCS_MCP_PORT=8000
AEQCS_CORE_PG_DSN=postgresql://aeqcs_mcp:CHANGE_ME@127.0.0.1:5432/aeqcs
AEQCS_MCP_POOL_SIZE=8
```

Keep this endpoint on loopback. If another process needs remote access, put that process on the same host or create a private tunnel with authentication outside AEQCS.

## MCP Tools

The current core tool boundary includes:

| Tool | Purpose | Required time boundary |
| --- | --- | --- |
| `get_market_data` | PIT market rows with pagination and dual adjusted-price fields where available | `as_of_date` |
| `get_financials` | PIT financial indicators from Tushare-derived chain | `as_of_date` |
| `get_index_constituents` | Historical index constituents visible at a given date | `as_of_date` |
| `submit_proposal` | Submit deterministic candidate changes to the gate | proposal payload timestamp |
| `get_proposal_status` | Read proposal state | proposal id |
| `review_proposal` | Review a proposal through the gate state machine | reviewer id |
| `approve_proposal` | Audited promotion boundary | approver id |
| `run_backtest` | Deterministic synchronous daily backtest for small jobs | `as_of_date` |
| `submit_backtest_task` | Create asynchronous MCP backtest task | `as_of_date` |
| `get_backtest_task` | Poll asynchronous backtest task status | task id |
| `get_backtest_result` | Read persisted backtest report | result id |
| `compute_factors` | Compute deterministic factors and persist values | `as_of_date` |
| `get_factor_values` | Query persisted factor values | `as_of_date` |
| `load_inbox` | Store text/Markdown documents into deterministic ingest path | document hash |
| `get_uploaded_doc` | Read uploaded document chunks | sha256 |
| `create_universe_node` | Create or update audited graph node | `as_of_date` |
| `create_universe_edge` | Create audited graph edge | valid date range |
| `verify_universe_edge` | Mark a graph edge verified | verifier and date |
| `retire_universe_edge` | Retire a graph edge from a date | valid-to date |
| `get_universe_children` | Read verified graph children visible as-of date | `as_of_date` |
| `search_semantic_nodes` | Search audited semantic nodes by text or embedding | query vector/model |
| `scan_intraday_events` | Deterministic CEP rule scan | event timestamps |
| `scan_drawdown_risk` | Deterministic NAV drawdown scan | NAV dates |
| `scan_portfolio_risk` | Deterministic exposure/concentration scan | portfolio date |
| `system_health` | Health, source registration, resource budget, tool manifest | current runtime |

Any tool that can influence research or trading must use explicit point-in-time input. Missing `as_of_date` should be treated as a caller bug.

## Hermes Client Contract

Hermes should configure AEQCS as an MCP SSE server:

```yaml
aeqcs_core:
  transport: sse
  url: http://127.0.0.1:8000/sse
```

Hermes may:

- read data through MCP tools,
- submit proposals,
- poll proposal and backtest status,
- subscribe or poll core events from PostgreSQL-owned event tables.

Hermes must not:

- write authoritative tables directly,
- bypass `submit_proposal` / `approve_proposal`,
- call any LLM path from inside AEQCS core,
- expect AEQCS core to wait for Hermes responses.

## Data Source Interfaces

Configured in `aeqcs/config/data_sources.yaml`:

```yaml
sources:
  daily: tushare
  financial: tushare
  minute: baostock
  daily_cross_check: baostock
```

Responsibilities:

- Tushare: authoritative PIT financial and daily market source.
- baostock: free historical minute source and daily cross-check source.
- baostock is not allowed to feed `financial_indicators` or downstream fundamental factors.

baostock adapter rules:

- uses `adjustflag=3` raw prices only,
- serializes all requests through a process-global lock,
- uses generic `RateLimiter` daily quota support,
- reconnects transparently when the session expires.

## Environment Variables

| Variable | Required | Used by | Description |
| --- | --- | --- | --- |
| `AEQCS_PG_DSN` | production yes | batch, intraday, maintenance, verification | Full AEQCS database role |
| `AEQCS_CORE_PG_DSN` | production yes | MCP server | Restricted MCP role |
| `AEQCS_MCP_TRANSPORT` | yes | MCP server | `sse` in production |
| `AEQCS_MCP_HOST` | yes | MCP server | `127.0.0.1` |
| `AEQCS_MCP_PORT` | yes | MCP server | `8000` by default |
| `AEQCS_MCP_POOL_SIZE` | yes | MCP server | Keep within PostgreSQL connection budget |
| `AEQCS_LOCAL_ROOT` | dev only | local store fallback | Local test store root |
| `TUSHARE_TOKEN` | data yes | Tushare adapter | PIT financial and daily source token |
| `AEQCS_RESTORE_PG_DSN` | ops yes | restore rehearsal | Isolated restore database |
| `AEQCS_ALERT_PG_DSN` | optional | risk alert verification | Defaults can mirror core DSN |
| `AEQCS_RECOVERY_PG_DSN` | optional | backtest recovery verification | Defaults can mirror core DSN |

## Common Commands

Start MCP manually:

```bash
cd /opt/aeqcs
.venv/bin/python -m aeqcs.core.mcp_server
```

Run end-of-day batch plan:

```bash
cd /opt/aeqcs
.venv/bin/python -m aeqcs.runtime.batch eod
```

Run night DAG plan:

```bash
cd /opt/aeqcs
.venv/bin/python -m aeqcs.runtime.batch night
```

Run intraday monitor:

```bash
cd /opt/aeqcs
.venv/bin/python -m aeqcs.runtime.intraday
```

Run a local smoke backtest:

```bash
cd /opt/aeqcs
.venv/bin/python -m aeqcs.runtime.batch smoke
```

Import a small Tushare slice into the local development store:

```bash
cd /opt/aeqcs
.venv/bin/python scripts/import_tushare_local.py \
  --symbol 000001.SZ \
  --start 2026-01-01 \
  --end 2026-01-31 \
  --token "$TUSHARE_TOKEN"
```

## Verification Commands

Local deterministic boundary:

```bash
.venv/bin/python -m scripts.verify_core_offline
```

Live MCP SSE endpoint:

```bash
.venv/bin/python -m scripts.verify_mcp_http_sse --endpoint http://127.0.0.1:8000/sse --connections 8
```

Restricted database grants:

```bash
.venv/bin/python -m scripts.verify_mcp_permissions
```

Backtest task recovery:

```bash
.venv/bin/python -m scripts.verify_mcp_backtest_recovery
```

Risk alert delivery through event bus:

```bash
.venv/bin/python -m scripts.verify_risk_alert_delivery
```

Table bloat check after at least four hours of intraday writes:

```bash
.venv/bin/python -m scripts.verify_table_bloat --dsn "$AEQCS_PG_DSN" --min-observed-hours 4
```
