# Linux Installation Guide

This guide installs AEQCS deterministic core on a single Ubuntu host. The target service layout is:

- code: `/opt/aeqcs`
- runtime data: `/data/aeqcs`
- environment file: `/etc/aeqcs/aeqcs.env`
- MCP endpoint: `http://127.0.0.1:8000/sse`
- service user: `aeqcs`

The core layer is intentionally local-first. Bind MCP to `127.0.0.1`; let Hermes or another trusted local client connect as the MCP client.

## 1. System Packages

Use Ubuntu 22.04 or 24.04 with Python 3.11.

```bash
sudo apt-get update
sudo apt-get install -y \
  git curl ca-certificates build-essential pkg-config \
  python3.11 python3.11-venv python3.11-dev \
  postgresql-client
```

If PostgreSQL/TimescaleDB runs on the same host, install PostgreSQL 15 or 16, TimescaleDB, and pgvector through your normal package source. Managed TimescaleDB is also supported; in that case this host only needs `postgresql-client`.

## 2. Service User And Directories

```bash
sudo useradd --system --create-home --home-dir /opt/aeqcs --shell /usr/sbin/nologin aeqcs
sudo mkdir -p /opt/aeqcs /data/aeqcs/{local,parquet,duckdb_tmp,inbox,docs,logs} /etc/aeqcs
sudo chown -R aeqcs:aeqcs /opt/aeqcs /data/aeqcs
sudo chmod 750 /opt/aeqcs /data/aeqcs /etc/aeqcs
```

## 3. Clone And Install

```bash
sudo -u aeqcs git clone https://github.com/Jackiedunk/AEQCS.git /opt/aeqcs
cd /opt/aeqcs
sudo -u aeqcs git checkout master
sudo -u aeqcs python3.11 -m venv .venv
sudo -u aeqcs .venv/bin/python -m pip install --upgrade pip wheel
sudo -u aeqcs .venv/bin/python -m pip install -e ".[data,qlib]"
```

For an offline or restricted host, build a wheelhouse on a connected machine first, then run the final install with `--no-index --find-links`.

## 4. Configure Environment

```bash
sudo cp /opt/aeqcs/deploy/aeqcs.env.example /etc/aeqcs/aeqcs.env
sudo chown root:aeqcs /etc/aeqcs/aeqcs.env
sudo chmod 640 /etc/aeqcs/aeqcs.env
sudo nano /etc/aeqcs/aeqcs.env
```

Set at least:

- `AEQCS_PG_DSN`: full database role for batch, ingestion, maintenance, and admin checks.
- `AEQCS_CORE_PG_DSN`: restricted `aeqcs_mcp` database role for MCP.
- `TUSHARE_TOKEN`: required for PIT financial data.
- `AEQCS_RESTORE_PG_DSN`: isolated restore rehearsal database.

Do not put secrets into Git or shell history. Prefer editing `/etc/aeqcs/aeqcs.env` directly on the target host.

## 5. Initialize Database

Run schema initialization with a PostgreSQL role that can create extensions, tables, indexes, and roles.

```bash
cd /opt/aeqcs
sudo -u aeqcs .venv/bin/python deploy/init_db.py "postgresql://postgres:CHANGE_ME@127.0.0.1:5432/aeqcs"
```

Required extensions:

- `timescaledb`
- `vector`

The initialization creates the core tables, Timescale hypertables, pgvector indexes, autovacuum table settings, the full `aeqcs_core` runtime role, and the restricted `aeqcs_mcp` role. After initialization, rotate the generated placeholder passwords and update `/etc/aeqcs/aeqcs.env`.

## 6. Install systemd Units

```bash
sudo cp /opt/aeqcs/deploy/systemd/*.service /etc/systemd/system/
sudo cp /opt/aeqcs/deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mcp-server.service
sudo systemctl enable --now intraday.timer batch-eod.timer batch-night.timer db-vacuum.timer restore-rehearsal.timer
```

Check status:

```bash
systemctl status mcp-server.service
journalctl -u mcp-server.service -n 100 --no-pager
```

## 7. Acceptance Checks

Run these after installation:

```bash
cd /opt/aeqcs
sudo -u aeqcs .venv/bin/python -m scripts.verify_core_offline
sudo -u aeqcs .venv/bin/python -m scripts.verify_mcp_http_sse --endpoint http://127.0.0.1:8000/sse --connections 8
sudo -u aeqcs bash -lc 'cd /opt/aeqcs && set -a && source /etc/aeqcs/aeqcs.env && set +a && .venv/bin/python -m scripts.verify_mcp_permissions'
sudo -u aeqcs bash -lc 'cd /opt/aeqcs && set -a && source /etc/aeqcs/aeqcs.env && set +a && .venv/bin/python -m scripts.verify_mcp_backtest_recovery'
sudo -u aeqcs .venv/bin/python -m aeqcs.runtime.batch smoke
```

Expected result: each verification script prints JSON with `status: "ok"` or exits successfully. If the managed database blocks role creation or extension creation, perform those steps through the provider console and rerun the verifier.

## 8. Upgrade

```bash
cd /opt/aeqcs
sudo systemctl stop mcp-server.service
sudo -u aeqcs git fetch origin
sudo -u aeqcs git checkout master
sudo -u aeqcs git pull --ff-only
sudo -u aeqcs .venv/bin/python -m pip install -e ".[data,qlib]"
sudo -u aeqcs .venv/bin/python deploy/init_db.py "postgresql://postgres:CHANGE_ME@127.0.0.1:5432/aeqcs"
sudo systemctl daemon-reload
sudo systemctl start mcp-server.service
sudo -u aeqcs .venv/bin/python -m scripts.verify_mcp_http_sse --endpoint http://127.0.0.1:8000/sse --connections 8
```

## 9. Notes For WSL2

WSL2 is suitable for development and integration testing. For production-like service management, use a Linux VM or server with systemd enabled. If WSL2 systemd is enabled, the same unit files work, but keep PostgreSQL and AEQCS data on the Linux filesystem rather than `/mnt/c`.
