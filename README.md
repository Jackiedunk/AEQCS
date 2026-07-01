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

## Linux Install From A Blank Host

This section is written for a fresh Ubuntu mini host with no AEQCS environment
prepared yet. Ubuntu 24.04 is recommended because its default Python is already
new enough. Ubuntu 22.04 also works, but you must install Python 3.11 or newer
first. Run the commands on the Linux host, not on Windows.

The finished normal state is:

- AEQCS code is in `/opt/aeqcs`.
- Runtime data is under `/data/aeqcs`.
- Secrets and DSNs are in `/etc/aeqcs/aeqcs.env`.
- PostgreSQL/TimescaleDB is running locally.
- `mcp-server.service` is running and bound to `127.0.0.1:8000`.
- `http://127.0.0.1:8000/sse` passes the MCP/SSE verifier.
- `pytest`, offline health, permissions, recovery, and smoke checks pass.

### 0. Start With A Clean Ubuntu Shell

Log in with a sudo-capable user and check the OS:

```bash
lsb_release -a
whoami
sudo -v
```

Expected: Ubuntu 22.04/24.04 and `sudo -v` exits without an error.

### 1. Install Basic System Packages

```bash
sudo apt-get update
sudo apt-get install -y \
  git curl ca-certificates gnupg lsb-release wget \
  build-essential pkg-config postgresql-common apt-transport-https \
  python3 python3-venv python3-dev
```

Check:

```bash
python3 --version
git --version
```

Expected: Python prints `3.11.x`, `3.12.x`, or newer, and Git prints a version.
If Python prints `3.10.x`, stop and install Python 3.11+ before continuing.

### 2. Install Local PostgreSQL + TimescaleDB

AEQCS needs PostgreSQL with the `timescaledb` extension. The commands below use
PostgreSQL 18 because that is the current upstream package line. If you choose a
different PostgreSQL major version, replace every `18` in this section with that
version. Official package references:

- PostgreSQL Ubuntu packages: <https://www.postgresql.org/download/linux/ubuntu/>
- TimescaleDB Linux install: <https://www.tigerdata.com/docs/self-hosted/latest/install/installation-linux/>

```bash
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
echo "deb https://packagecloud.io/timescale/timescaledb/ubuntu/ $(lsb_release -c -s) main" \
  | sudo tee /etc/apt/sources.list.d/timescaledb.list
wget --quiet -O - https://packagecloud.io/timescale/timescaledb/gpgkey \
  | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/timescaledb.gpg
sudo apt-get update
sudo apt-get install -y postgresql-18 postgresql-client-18 postgresql-18-pgvector timescaledb-2-postgresql-18
sudo timescaledb-tune
sudo systemctl restart postgresql
sudo systemctl enable postgresql
```

Set a password for the local `postgres` admin user. Save it in your password
manager; do not commit it to Git.

```bash
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'CHANGE_ME_POSTGRES_ADMIN_PASSWORD';"
```

Create the AEQCS production database and an isolated restore rehearsal database:

```bash
sudo -u postgres createdb aeqcs
sudo -u postgres createdb aeqcs_restore
sudo -u postgres psql -d aeqcs -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
sudo -u postgres psql -d aeqcs -c "CREATE EXTENSION IF NOT EXISTS vector;"
sudo -u postgres psql -d aeqcs_restore -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
sudo -u postgres psql -d aeqcs_restore -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Check:

```bash
sudo -u postgres psql -d aeqcs -c "\dx"
```

Expected: the extension list includes `timescaledb` and `vector`.

### 3. Download AEQCS Into `/opt/aeqcs`

```bash
sudo mkdir -p /opt
sudo git clone https://github.com/Jackiedunk/AEQCS.git /opt/aeqcs
cd /opt/aeqcs
sudo git checkout master
```

Check:

```bash
git status -sb
```

Expected: `## master...origin/master` with no modified files.

### 4. Run The Installer

```bash
cd /opt/aeqcs
sudo AEQCS_PYTHON_BIN=python3 bash deploy/install_linux.sh
```

This creates:

- Linux service user: `aeqcs`
- Python virtual environment: `/opt/aeqcs/.venv`
- Data directories: `/data/aeqcs/...`
- Environment template: `/etc/aeqcs/aeqcs.env`
- systemd unit files

Check:

```bash
id aeqcs
ls -ld /opt/aeqcs /data/aeqcs /etc/aeqcs
test -x /opt/aeqcs/.venv/bin/python
```

Expected: all commands succeed.

### 5. Configure Secrets And Database URLs

Open the environment file:

```bash
sudo nano /etc/aeqcs/aeqcs.env
```

Set these values. Replace passwords and token placeholders with your real
values.

```bash
AEQCS_ENV=production
AEQCS_LOG_LEVEL=INFO

AEQCS_PG_DSN=postgresql://aeqcs_core:CHANGE_ME_AEQCS_CORE@127.0.0.1:5432/aeqcs
AEQCS_CORE_PG_DSN=postgresql://aeqcs_mcp:CHANGE_ME_AEQCS_MCP@127.0.0.1:5432/aeqcs
AEQCS_RESTORE_PG_DSN=postgresql://aeqcs_restore:CHANGE_ME_AEQCS_RESTORE@127.0.0.1:5432/aeqcs_restore
AEQCS_ALERT_PG_DSN=postgresql://aeqcs_mcp:CHANGE_ME_AEQCS_MCP@127.0.0.1:5432/aeqcs
AEQCS_RECOVERY_PG_DSN=postgresql://aeqcs_mcp:CHANGE_ME_AEQCS_MCP@127.0.0.1:5432/aeqcs

AEQCS_MCP_TRANSPORT=sse
AEQCS_MCP_HOST=127.0.0.1
AEQCS_MCP_PORT=8000
AEQCS_MCP_POOL_SIZE=8
AEQCS_LOCAL_ROOT=/data/aeqcs/local

TUSHARE_TOKEN=CHANGE_ME_TUSHARE_TOKEN
```

Protect it:

```bash
sudo chown root:aeqcs /etc/aeqcs/aeqcs.env
sudo chmod 640 /etc/aeqcs/aeqcs.env
```

### 6. Initialize AEQCS Database Schema And Roles

Use the local `postgres` admin URL here. This command creates AEQCS tables,
hypertables, indexes, and runtime roles.

```bash
cd /opt/aeqcs
sudo -u aeqcs .venv/bin/python deploy/init_db.py \
  "postgresql://postgres:CHANGE_ME_POSTGRES_ADMIN_PASSWORD@127.0.0.1:5432/aeqcs"
```

If `deploy/init_db.py` prints generated passwords or role-change instructions,
copy them into `/etc/aeqcs/aeqcs.env` and rerun the command once. It is designed
to be safe to rerun.

Check:

```bash
sudo -u postgres psql -d aeqcs -c "\dt"
sudo -u postgres psql -d aeqcs -c "\du"
```

Expected: AEQCS tables exist, and roles such as `aeqcs_core` and `aeqcs_mcp`
exist.

### 7. Start Services

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mcp-server.service
sudo systemctl enable --now intraday.timer batch-eod.timer batch-night.timer db-vacuum.timer restore-rehearsal.timer
```

Check:

```bash
systemctl status mcp-server.service --no-pager
ss -ltnp | grep ':8000'
journalctl -u mcp-server.service -n 80 --no-pager
```

Expected:

- `mcp-server.service` is `active (running)`.
- Port `127.0.0.1:8000` is listening.
- Logs show Uvicorn running and no traceback.

### 8. Run Acceptance Checks

Load the environment and run the checks as the `aeqcs` service user:

```bash
cd /opt/aeqcs
sudo -u aeqcs bash -lc 'cd /opt/aeqcs && set -a && source /etc/aeqcs/aeqcs.env && set +a && .venv/bin/python -m pytest -q'
sudo -u aeqcs bash -lc 'cd /opt/aeqcs && set -a && source /etc/aeqcs/aeqcs.env && set +a && .venv/bin/python -m scripts.verify_core_offline'
sudo -u aeqcs bash -lc 'cd /opt/aeqcs && set -a && source /etc/aeqcs/aeqcs.env && set +a && .venv/bin/python -m scripts.verify_mcp_http_sse --endpoint http://127.0.0.1:8000/sse --connections 8'
sudo -u aeqcs bash -lc 'cd /opt/aeqcs && set -a && source /etc/aeqcs/aeqcs.env && set +a && .venv/bin/python -m scripts.verify_mcp_permissions'
sudo -u aeqcs bash -lc 'cd /opt/aeqcs && set -a && source /etc/aeqcs/aeqcs.env && set +a && .venv/bin/python -m scripts.verify_mcp_backtest_recovery'
sudo -u aeqcs bash -lc 'cd /opt/aeqcs && set -a && source /etc/aeqcs/aeqcs.env && set +a && .venv/bin/python -m scripts.verify_risk_alert_delivery'
sudo -u aeqcs bash -lc 'cd /opt/aeqcs && set -a && source /etc/aeqcs/aeqcs.env && set +a && .venv/bin/python -m aeqcs.runtime.batch smoke'
```

Expected normal result:

- `pytest` ends with all tests passed and only intentional skips.
- verifier scripts print JSON with `"status": "ok"` or exit successfully.
- MCP/SSE verifier reports zero failures.
- smoke backtest exits successfully.

### 9. Run A Small Real Data Test

This verifies that Tushare credentials and the LocalStore path work. It pulls a
tiny sample only.

```bash
cd /opt/aeqcs
sudo -u aeqcs bash -lc 'cd /opt/aeqcs && set -a && source /etc/aeqcs/aeqcs.env && set +a && .venv/bin/python scripts/import_tushare_local.py --symbol 000001.SZ --start 2024-01-02 --end 2024-01-10 --root /data/aeqcs/local/e2e-smoke'
ls -lh /data/aeqcs/local/e2e-smoke
```

Expected: CSV files such as `stock_daily_origin.csv` and
`financial_indicators.csv` exist.

### 10. What "Everything Is Normal" Means

The install is considered healthy when all of these are true:

- `git -C /opt/aeqcs status -sb` shows clean `master`.
- `/etc/aeqcs/aeqcs.env` exists and is `640`.
- `systemctl status postgresql` is running.
- `systemctl status mcp-server.service` is running.
- `ss -ltnp | grep ':8000'` shows local port `127.0.0.1:8000`.
- `python -m pytest -q` passes.
- `scripts.verify_mcp_http_sse` reports `"status": "ok"`.
- `scripts.verify_mcp_permissions` reports `"status": "ok"`.
- `scripts.verify_mcp_backtest_recovery` reports `"status": "ok"`.
- `scripts.verify_risk_alert_delivery` reports `"status": "ok"`.
- A small Tushare import writes rows to `/data/aeqcs/local/e2e-smoke`.

The default MCP endpoint for Hermes or another trusted local client is:

```text
http://127.0.0.1:8000/sse
```

### 11. Common Beginner Problems

- Python prints `3.10.x`: install Python 3.11 or newer, or use Ubuntu 24.04 where `python3` is new enough.
- `CREATE EXTENSION timescaledb` fails: TimescaleDB package is not installed or PostgreSQL was not restarted after `timescaledb-tune`.
- `CREATE EXTENSION vector` fails: install the matching `postgresql-18-pgvector` package or use the package matching your PostgreSQL version.
- MCP service starts then exits: check `/etc/aeqcs/aeqcs.env` DSNs and `journalctl -u mcp-server.service -n 100 --no-pager`.
- Tushare import fails: check `TUSHARE_TOKEN`, network access, and token quota.
- Port 8000 is not listening: run `sudo systemctl restart mcp-server.service` and inspect the journal.

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

- local suite on current `master`: `483 passed, 3 skipped`
- real TimescaleDB integration, permissions, MCP recovery, risk-alert delivery, and SSE probes have passed in the development acceptance environment
- full production deployment acceptance still requires the target Linux/systemd/cgroup host run; see [docs/PRODUCTION_ACCEPTANCE.md](docs/PRODUCTION_ACCEPTANCE.md)
