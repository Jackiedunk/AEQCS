#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${AEQCS_REPO_DIR:-/opt/aeqcs}"
DATA_DIR="${AEQCS_DATA_DIR:-/data/aeqcs}"
ENV_DIR="${AEQCS_ENV_DIR:-/etc/aeqcs}"
SERVICE_USER="${AEQCS_SERVICE_USER:-aeqcs}"
PYTHON_BIN="${AEQCS_PYTHON_BIN:-python3.11}"
INSTALL_EXTRAS="${AEQCS_INSTALL_EXTRAS:-data,qlib}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "run as root: sudo bash deploy/install_linux.sh" >&2
  exit 1
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "${PYTHON_BIN} is required before running this installer" >&2
  exit 1
fi

if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "${REPO_DIR}" --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

mkdir -p "${REPO_DIR}" "${DATA_DIR}"/{local,parquet,duckdb_tmp,inbox,docs,logs} "${ENV_DIR}"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${REPO_DIR}" "${DATA_DIR}"
chmod 750 "${REPO_DIR}" "${DATA_DIR}" "${ENV_DIR}"

cd "${REPO_DIR}"

if [[ ! -d .venv ]]; then
  sudo -u "${SERVICE_USER}" "${PYTHON_BIN}" -m venv .venv
fi

sudo -u "${SERVICE_USER}" .venv/bin/python -m pip install --upgrade pip wheel
sudo -u "${SERVICE_USER}" .venv/bin/python -m pip install -e ".[${INSTALL_EXTRAS}]"

if [[ ! -f "${ENV_DIR}/aeqcs.env" ]]; then
  cp deploy/aeqcs.env.example "${ENV_DIR}/aeqcs.env"
  chown root:"${SERVICE_USER}" "${ENV_DIR}/aeqcs.env"
  chmod 640 "${ENV_DIR}/aeqcs.env"
  echo "created ${ENV_DIR}/aeqcs.env; edit secrets and DSNs before starting services"
fi

cp deploy/systemd/*.service /etc/systemd/system/
cp deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload

echo "AEQCS install files are in place."
echo "Next:"
echo "  1. edit ${ENV_DIR}/aeqcs.env"
echo "  2. initialize PostgreSQL with deploy/init_db.py"
echo "  3. run: systemctl enable --now mcp-server.service"
